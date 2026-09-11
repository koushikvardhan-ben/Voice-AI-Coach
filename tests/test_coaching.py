"""Regression coverage for continuous speech, request cancellation, and freshness."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.models import CallStatus, CoachState, Speaker, TranscriptTurn
from app.services.coach import schedule_coaching, _parse_coach, _build_user_prompt
from app.services.llm import GroqLLM, LLMError, LLMRateLimited
from app.services.session import CallSession


def response(move='Confirm the asking price and unit before discussing comparables.'):
    return dict(stage='discovery', customer_role='seller', sentiment='neutral', temperature=40,
                next_move=move, rationale='The seller just gave an unclear price.', running_summary='Land sale; clarify the price unit.')


class CoachingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = CallSession('coach-test')
        self.session.status = CallStatus.CONNECTED
        self.patches = [patch.object(settings, 'coach_debounce_seconds', .02),
                        patch.object(settings, 'coach_min_interval_seconds', .04),
                        patch.object(settings, 'coach_timeout_seconds', .06)]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        await self.session.cancel_tasks()
        for item in self.patches:
            item.stop()

    def speech(self, text, speaker=Speaker.CUSTOMER):
        self.session.append_final(TranscriptTurn(id=str(self.session.next_seq()), seq=self.session._seq,
                                                 speaker=speaker, text=text, is_final=True))
        schedule_coaching(self.session)

    async def test_continuous_speech_does_not_cancel_generation_or_starve_next_update(self):
        started, release, next_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        requests = []
        async def complete(system, user, **kwargs):
            requests.append(user)
            if len(requests) == 1:
                started.set()
                await release.wait()
                return response('Ask what price the seller expects.')
            next_started.set()
            return response()
        client = SimpleNamespace(complete_json=complete)
        with patch('app.services.coach.get_llm', return_value=client):
            self.speech('I am selling land with electricity and road access.')
            worker = self.session.debounce_task
            await asyncio.wait_for(started.wait(), .2)
            self.speech('What price are you hoping for?', Speaker.AGENT)
            self.speech('Twenty lakhs per square yard.')
            self.assertIs(self.session.debounce_task, worker)
            self.assertFalse(worker.cancelling())
            release.set()
            await asyncio.wait_for(next_started.wait(), .3)
            await worker
        self.assertEqual(len(requests), 2)
        self.assertIn('Twenty lakhs per square yard.', requests[1])
        self.assertIn('What price are you hoping for?', requests[1])
        self.assertEqual(self.session.coach_state.based_on_revision, 3)
        self.assertEqual(self.session.coach_state.stage, 'discovery')
        self.assertEqual(self.session.coach_status['state'], 'current')

    async def test_new_segments_do_not_restart_the_initial_coalescing_window(self):
        client = SimpleNamespace(complete_json=AsyncMock(return_value=response()))
        with patch('app.services.coach.get_llm', return_value=client):
            self.speech('Land for sale.')
            worker = self.session.debounce_task
            for _ in range(5):
                self.speech('There is road access.')
                self.assertIs(self.session.debounce_task, worker)
            await asyncio.wait_for(worker, .2)
        self.assertEqual(client.complete_json.await_count, 1)
        self.assertEqual(self.session.coach_state.based_on_revision, 6)

    async def test_agent_question_triggers_followup_after_customer_context_exists(self):
        client = SimpleNamespace(complete_json=AsyncMock(return_value=response()))
        with patch('app.services.coach.get_llm', return_value=client):
            self.speech('Hello.', Speaker.AGENT)
            self.assertIsNone(self.session.debounce_task)
            self.speech('I want to sell land.')
            await self.session.debounce_task
            self.speech('What price are you hoping for?', Speaker.AGENT)
            await self.session.debounce_task
        self.assertEqual(client.complete_json.await_count, 2)
        self.assertIn('What price are you hoping for?', client.complete_json.call_args.args[1])

    async def test_timeout_is_visible_and_retried_only_once_without_more_speech(self):
        async def hang(*args, **kwargs):
            await asyncio.Event().wait()
        client = SimpleNamespace(complete_json=AsyncMock(side_effect=hang))
        with patch('app.services.coach.get_llm', return_value=client):
            self.speech('My land is for sale.')
            await asyncio.wait_for(self.session.debounce_task, .5)
        self.assertEqual(client.complete_json.await_count, 2)
        self.assertEqual(self.session.coach_status['state'], 'error')
        self.assertIn('timed out', self.session.coach_status['message'])
        self.assertIsNone(self.session.coach_state)
        self.assertIsNone(self.session.debounce_task)

    async def test_rate_limit_preserves_backoff_when_more_speech_arrives(self):
        client = SimpleNamespace(complete_json=AsyncMock(side_effect=LLMRateLimited(30)))
        with patch('app.services.coach.get_llm', return_value=client):
            self.speech('Land for sale.')
            await asyncio.sleep(.03)
            deadline = self.session.coach_retry_at
            self.assertEqual(self.session.coach_status['state'], 'rate_limited')
            self.speech('I also have road access.')
            await asyncio.sleep(.03)
            self.assertEqual(client.complete_json.await_count, 1)
            self.assertEqual(self.session.coach_retry_at, deadline)
            self.assertEqual(self.session.coach_status['state'], 'rate_limited')

    async def test_hangup_cancels_worker_and_prevents_late_card_update(self):
        started = asyncio.Event()
        async def hang(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        with patch('app.services.coach.get_llm', return_value=SimpleNamespace(complete_json=hang)):
            self.speech('Land for sale.')
            await asyncio.wait_for(started.wait(), .2)
            self.session.begin_closing()
            await self.session.cancel_tasks()
            schedule_coaching(self.session)
        self.assertIsNone(self.session.coach_state)
        self.assertIsNone(self.session.debounce_task)

    def test_invalid_output_cannot_masquerade_as_refreshed_old_card(self):
        self.session.coach_state = CoachState(**response(), updated_at=1)
        for data in [{}, {'next_move': 'Ask again'}, {**response(), 'next_move': ''}, {**response(), 'stage': 'bad'}]:
            with self.subTest(data=list(data)):
                with self.assertRaises(ValueError):
                    _parse_coach(self.session, data)
        self.assertEqual(self.session.coach_state.updated_at, 1)

    def test_update_timestamp_and_revision_are_owned_by_server(self):
        with patch('app.services.coach.time.time', return_value=100):
            result = _parse_coach(self.session, {**response(), 'updated_at': 1, 'based_on_revision': 999})
        self.assertEqual(result.updated_at, 100)
        self.assertEqual(result.based_on_revision, 0)

    def test_prompt_includes_previous_action_for_completion_check(self):
        self.session.coach_state = CoachState(**response('Ask the seller for their asking price.'))
        prompt = _build_user_prompt(self.session)
        self.assertIn('Ask the seller for their asking price.', prompt)
        self.assertIn('Do not ask again for information already supplied', prompt)


class LLMOutputTests(unittest.IsolatedAsyncioTestCase):
    def client(self, *, content='{}', finish_reason='stop', model='openai/gpt-oss-120b'):
        client = GroqLLM.__new__(GroqLLM)
        client.model = model
        create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            finish_reason=finish_reason, message=SimpleNamespace(content=content))]))
        client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        return client, create

    async def test_reasoning_model_gets_room_for_json_and_lower_effort(self):
        client, create = self.client()
        await client.complete_json('system', 'user', 350)
        self.assertEqual(create.call_args.kwargs['reasoning_effort'], 'low')
        self.assertEqual(create.call_args.kwargs['max_completion_tokens'], 1024)

    async def test_other_models_do_not_receive_unsupported_reasoning_options(self):
        client, create = self.client(model='other-model')
        await client.complete_json('system', 'user', 350)
        self.assertNotIn('reasoning_effort', create.call_args.kwargs)
        self.assertEqual(create.call_args.kwargs['max_completion_tokens'], 350)

    async def test_empty_truncated_and_non_object_answers_are_errors(self):
        for content, reason in [('', 'stop'), ('{}', 'length'), ('[]', 'stop'), ('partial json', 'stop')]:
            with self.subTest(content=content, reason=reason):
                client, _ = self.client(content=content, finish_reason=reason)
                with self.assertRaises(LLMError):
                    await client.complete_json('system', 'user', 350)
