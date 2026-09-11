"""Streaming regressions; fake provider sockets, no network or speech API calls."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from app.config import settings
from app.models import Speaker
from app.services.deepgram_client import DeepgramTrack
from app.services.session import CallSession
from app.services.transcript import TrackTranscriber


def events(session):
    items = []
    while not session.out_queue.empty():
        items.append(session.out_queue.get_nowait())
    return items


class TranscriptTests(unittest.TestCase):
    def test_confirmed_segment_is_visible_before_silence_and_updated_in_place(self):
        session = CallSession('finals')
        tx = TrackTranscriber(session, Speaker.CUSTOMER)
        tx.on_results('My budget is', True, False)
        self.assertEqual(session.turns[0].text, 'My budget is')
        first = events(session)[0]['turn']
        tx.on_results('eighty five lakh.', True, True)
        second = events(session)[0]['turn']
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['text'], 'My budget is')  # old events are snapshots
        self.assertEqual(second['text'], 'My budget is eighty five lakh.')
        self.assertEqual(len(session.turns), 1)

    def test_interims_do_not_enter_history_or_repeat_confirmed_words(self):
        session = CallSession('partials')
        tx = TrackTranscriber(session, Speaker.AGENT)
        tx.on_results('Please confirm', True, False)
        tx.on_results('the viewing time', False, False)
        self.assertEqual(session.turns[0].text, 'Please confirm')
        self.assertEqual(session.interim[Speaker.AGENT], 'the viewing time')
        tx.on_results('', False, False)
        self.assertNotIn(Speaker.AGENT, session.interim)
        self.assertEqual(events(session)[-1]['turn']['text'], '')

    def test_stream_boundary_retains_finals_but_never_promotes_uncertain_text(self):
        session = CallSession('boundary')
        tx = TrackTranscriber(session, Speaker.CUSTOMER)
        tx.on_results('I need', True, False)
        tx.on_results('a guaranteed loan', False, False)
        tx.on_utterance_end()
        tx.on_results('a viewing.', True, True)
        self.assertEqual([t.text for t in session.turns], ['I need', 'a viewing.'])


class FakeSocket:
    def __init__(self, *, block_audio=False, fail_audio=False):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.audio_started = asyncio.Event()
        self.audio_sent = asyncio.Event()
        self.close_requested = asyncio.Event()
        self.release_audio = asyncio.Event()
        if not block_audio:
            self.release_audio.set()
        self.fail_audio = fail_audio
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.incoming.get()
        if message is None:
            raise StopAsyncIteration
        return json.dumps(message)

    async def send(self, payload):
        if isinstance(payload, bytes):
            self.audio_started.set()
            await self.release_audio.wait()
            if self.fail_audio:
                raise OSError('simulated connection drop')
            self.sent.append(payload)
            self.audio_sent.set()
        else:
            self.sent.append(payload)
            if json.loads(payload)['type'] == 'CloseStream':
                self.close_requested.set()

    async def close(self):
        if not self.closed:
            self.closed = True
            self.incoming.put_nowait(None)


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key_patch = patch.object(settings, 'deepgram_api_key', 'fake-unit-test-key')
        self.key_patch.start()
        self.runners = []

    async def asyncTearDown(self):
        for task in self.runners:
            task.cancel()
        await asyncio.gather(*self.runners, return_exceptions=True)
        self.key_patch.stop()

    def track(self, speaker=Speaker.AGENT):
        return DeepgramTrack(speaker, TrackTranscriber(CallSession('unit'), speaker))

    def run_track(self, track):
        task = asyncio.create_task(track.run())
        self.runners.append(task)
        return task

    async def test_startup_buffers_audio_and_sends_every_packet_in_order(self):
        track, socket = self.track(), FakeSocket()
        release_connect = asyncio.Event()
        async def connect(*args, **kwargs):
            await release_connect.wait()
            return socket
        with patch('app.services.deepgram_client.websockets.connect', side_effect=connect):
            self.run_track(track)
            await track.send(b'first')
            await track.send(b'second')
            self.assertEqual(socket.sent, [])
            release_connect.set()
            await asyncio.wait_for(track._queue.join(), .5)
            self.assertEqual(socket.sent, [b'first', b'second'])

    async def test_blocked_agent_does_not_hold_up_customer_audio(self):
        agent, customer = self.track(), self.track(Speaker.CUSTOMER)
        slow, fast = FakeSocket(block_audio=True), FakeSocket()
        with patch('app.services.deepgram_client.websockets.connect', new_callable=AsyncMock, side_effect=[slow, fast]):
            self.run_track(agent)
            await agent.send(b'agent')
            await asyncio.wait_for(slow.audio_started.wait(), .5)
            self.run_track(customer)
            await asyncio.wait_for(customer.send(b'customer'), .1)
            await asyncio.wait_for(fast.audio_sent.wait(), .5)
            self.assertEqual(fast.sent, [b'customer'])
            self.assertEqual(slow.sent, [])

    async def test_long_outage_has_bounded_buffer_and_an_explicit_gap_notice(self):
        track = self.track()
        track._max_bytes = 8
        await track.send(b'1111')
        await track.send(b'2222')
        await track.send(b'3333')
        self.assertEqual(track._queued_bytes, 8)
        self.assertEqual(track._queue.get_nowait()[0], b'2222')
        self.assertEqual(track._queue.get_nowait()[0], b'3333')
        self.assertEqual(track._dropped_bytes, 4)
        self.assertTrue(any(e['type'] == 'notice' for e in events(track.transcriber.session)))

    async def test_short_reconnect_retains_pending_audio_without_replaying_failed_frame(self):
        track, broken, recovered = self.track(), FakeSocket(fail_audio=True), FakeSocket()
        with patch('app.services.deepgram_client.websockets.connect', new_callable=AsyncMock, side_effect=[broken, recovered]):
            self.run_track(track)
            await track.send(b'uncertain-delivery')
            await asyncio.wait_for(broken.audio_started.wait(), .5)
            await track.send(b'next-words')
            await asyncio.wait_for(recovered.audio_sent.wait(), 1)
            self.assertEqual(recovered.sent, [b'next-words'])
            self.assertEqual(track._dropped_bytes, len(b'uncertain-delivery'))

    async def test_finish_waits_for_provider_tail_before_closing_socket(self):
        track, socket = self.track(), FakeSocket()
        with patch('app.services.deepgram_client.websockets.connect', AsyncMock(return_value=socket)):
            self.run_track(track)
            await track.send(b'last-words-audio')
            await asyncio.wait_for(socket.audio_sent.wait(), .5)
            finish = asyncio.create_task(track.finish())
            await asyncio.wait_for(socket.close_requested.wait(), .5)
            self.assertFalse(finish.done())
            self.assertFalse(socket.closed)
            socket.incoming.put_nowait({'type': 'Results', 'channel': {'alternatives': [{'transcript': 'See you Saturday.'}]}, 'is_final': True, 'speech_final': True})
            socket.incoming.put_nowait(None)
            await asyncio.wait_for(finish, .5)
            self.assertEqual(track.transcriber.session.turns[0].text, 'See you Saturday.')

    async def test_url_keeps_phone_audio_format_and_configures_low_latency(self):
        track = self.track()
        track.language, track.keyterms = 'multi', ['Jubilee Hills', 'RERA']
        with patch.object(settings, 'deepgram_model', 'nova-3'):
            params = parse_qs(urlsplit(track._url()).query)
        self.assertEqual(params['encoding'], ['mulaw'])
        self.assertEqual(params['sample_rate'], ['8000'])
        self.assertEqual(params['channels'], ['1'])
        self.assertEqual(params['language'], ['multi'])
        self.assertEqual(params['keyterm'], ['Jubilee Hills', 'RERA'])
        self.assertEqual(params['interim_results'], ['true'])
        self.assertEqual(params['smart_format'], ['false'])
        self.assertEqual(params['endpointing'], [str(settings.stt_endpointing_ms)])

    async def test_unsupported_keyterm_model_does_not_receive_nova3_option(self):
        track = self.track()
        track.keyterms = ['BHK']
        with patch.object(settings, 'deepgram_model', 'nova-2'):
            self.assertNotIn('keyterm', parse_qs(urlsplit(track._url()).query))

    async def test_result_delay_uses_audio_boundary_not_call_start_or_silence(self):
        track = self.track()
        track._first_audio_at = 1
        track._audio_clock.extend([(.02, 90), (.04, 99.4), (.06, 99.5)])
        with patch('app.services.deepgram_client.time.monotonic', return_value=100):
            track._handle({'type': 'Results', 'start': 0, 'duration': .04,
                           'channel': {'alternatives': [{'transcript': 'Hello'}]}})
        state = track.transcriber.session.stt_state['agent']
        self.assertEqual(state['result_age_ms'], 600)
        self.assertEqual(state['buffered_ms'], 0)


if __name__ == '__main__':
    unittest.main()
