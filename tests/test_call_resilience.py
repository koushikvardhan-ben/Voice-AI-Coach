"""Telephony lifetime is independent of transcription and browser update sockets."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import WebSocketDisconnect

from app.config import settings
from app.models import CallStatus
from app.routes.twiml import twiml_status
from app.services.session import CallSession, session_manager
from app.services.telephony import _recover_media, schedule_media_recovery
from app.ws.media import media_ws
from app.ws.browser import browser_ws


class MediaSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.close = AsyncMock()
        self.accept = AsyncMock()
        self.send_json = AsyncMock()

    async def receive_text(self):
        item = next(self.messages)
        if isinstance(item, Exception):
            raise item
        return json.dumps(item)


class CallResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = CallSession("resilience")
        self.session.status = CallStatus.CONNECTED
        self.session.parent_call_sid = "CA" + "1" * 32
        session_manager._sessions[self.session.call_id] = self.session

    async def asyncTearDown(self):
        await self.session.cancel_tasks()
        session_manager._sessions.clear()

    async def test_media_stop_and_socket_failure_do_not_end_the_phone_call(self):
        for terminal in [{"event": "stop"}, WebSocketDisconnect(code=1006)]:
            with self.subTest(terminal=type(terminal).__name__):
                agent, customer = Mock(), Mock()
                agent.finish = AsyncMock()
                customer.finish = AsyncMock()
                self.session.dg_agent, self.session.dg_customer = agent, customer
                socket = MediaSocket([terminal])
                with patch("app.ws.media.start_transcription"), patch("app.ws.media.schedule_media_recovery") as recover:
                    await media_ws(socket, self.session.call_id)
                self.assertEqual(self.session.status, CallStatus.CONNECTED)
                self.assertFalse(self.session.closing)
                self.assertFalse(self.session.summary_sent)
                self.assertIs(session_manager.get(self.session.call_id), self.session)
                recover.assert_called_once_with(self.session)
                agent.finish.assert_awaited_once()
                customer.finish.assert_awaited_once()

    async def test_late_media_socket_does_not_resurrect_an_ended_call(self):
        socket = MediaSocket([])
        await media_ws(socket, "already-removed")
        socket.close.assert_awaited_once_with(code=1008)
        self.assertIsNone(session_manager.get("already-removed"))

    async def test_status_callback_returns_before_slow_finalization(self):
        request = Mock(query_params={"callId": self.session.call_id})
        request.form = AsyncMock(return_value={"CallStatus": "completed"})
        release = asyncio.Event()
        async def slow_finalize(*args):
            await release.wait()
        with patch("app.services.lifecycle.teardown_call", side_effect=slow_finalize) as finalize:
            response = await asyncio.wait_for(twiml_status(request), .1)
            self.assertEqual(response.status_code, 204)
            self.assertEqual(self.session.status, CallStatus.ENDED)
            self.assertFalse(self.session.teardown_task.done())
            await twiml_status(request)
            release.set()
            await self.session.teardown_task
            self.assertEqual(finalize.call_count, 1)

    async def test_browser_socket_disconnect_is_not_a_phone_disconnect(self):
        socket = MediaSocket([WebSocketDisconnect(code=1006)])
        with patch("app.ws.browser.schedule_teardown") as finalize:
            await browser_ws(socket, self.session.call_id)
        finalize.assert_not_called()
        self.assertEqual(self.session.status, CallStatus.CONNECTED)

    async def test_sdk_disconnect_finalizes_but_reconnecting_does_not(self):
        socket = MediaSocket([
            {"type": "sdk_event", "event": "reconnecting", "code": 53001},
            {"type": "sdk_event", "event": "error", "code": 53001, "closed": False},
            {"type": "sdk_event", "event": "disconnect"},
            WebSocketDisconnect(code=1000),
        ])
        with patch("app.ws.browser.schedule_teardown") as finalize:
            await browser_ws(socket, self.session.call_id)
        finalize.assert_called_once_with(self.session, "browser_disconnect")
        self.assertEqual([d["event"] for d in self.session.diagnostics], ["reconnecting", "error", "disconnect"])

    async def recover(self, handler):
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        with patch("app.services.telephony.httpx.AsyncClient", return_value=client), \
             patch("app.services.telephony.asyncio.sleep", new=AsyncMock()), \
             patch.object(settings, "twilio_auth_token", "fake-unit-test-key"):
            await _recover_media(self.session)

    async def test_recovery_restarts_only_audio_fork_never_updates_or_hangs_up_call(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(200, json={"status": "in-progress"})
            self.session.media_ws = Mock()
            return httpx.Response(201, json={"sid": "MZreplacement"})
        await self.recover(handler)
        self.assertEqual([r.method for r in requests], ["GET", "POST"])
        self.assertTrue(requests[1].url.path.endswith("/Streams.json"))
        self.assertIn(b"Track=both_tracks", requests[1].content)
        self.assertNotIn(b"Status=completed", requests[1].content)
        self.assertEqual(self.session.status, CallStatus.CONNECTED)

    async def test_recovery_finalizes_if_twilio_confirms_actual_hangup(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            return httpx.Response(200, json={"status": "completed"})
        with patch("app.services.telephony.schedule_teardown") as finalize:
            await self.recover(handler)
        finalize.assert_called_once_with(self.session, "completed")

    async def test_recovery_auth_failure_does_not_end_call(self):
        await self.recover(lambda request: httpx.Response(401))
        self.assertFalse(self.session.closing)
        self.assertEqual(self.session.status, CallStatus.CONNECTED)
        self.assertEqual(self.session.diagnostics[-1]["http_status"], 401)

    async def test_duplicate_stream_callbacks_cannot_exceed_recovery_limit(self):
        self.session.media_recovery_attempts = 3
        with patch("app.services.telephony._recover_media") as recover:
            schedule_media_recovery(self.session)
            schedule_media_recovery(self.session)
        recover.assert_not_called()
        self.assertIsNone(self.session.media_recovery)

    async def test_old_track_cleanup_cannot_race_a_replacement_socket(self):
        self.session.media_cleanup = True
        socket = MediaSocket([])
        await media_ws(socket, self.session.call_id)
        socket.close.assert_awaited_once_with(code=1008)
        self.assertFalse(self.session.closing)
