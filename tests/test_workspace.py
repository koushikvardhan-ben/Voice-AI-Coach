import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app import db
from app.config import settings
from app.main import create_app
from app.models import CallStatus, CallSummary, Speaker, TranscriptTurn
from app.services.coach import _build_user_prompt
from app.services.deepgram_client import DeepgramTrack
from app.services.lifecycle import teardown_call
from app.services.session import CallSession, session_manager
from app.services.transcript import TrackTranscriber
from app.rag.knowledge import relevant_context


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.prewarm = patch("app.ws.media.start_transcription").start()
        self.tmp = tempfile.TemporaryDirectory()
        self.original = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        self.client = TestClient(create_app())
        self.client.__enter__()
        session_manager._sessions.clear()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        db.DB_PATH = self.original
        self.tmp.cleanup()
        session_manager._sessions.clear()
        patch.stopall()

    def test_profiles_and_knowledge_persist_and_detach(self):
        doc = self.client.post("/api/knowledge", json={"title": "Verified listing", "content": "Asking price: 92 lakh."}).json()
        profile = self.client.post("/api/agents", json={"name": "Buyer test", "knowledge_ids": [doc["id"]]}).json()
        self.assertIn(profile["id"], [x["id"] for x in db.list_records("agents")])
        result = self.client.put(f"/api/agents/{profile['id']}", json={**profile, "instructions": "Clarify the total budget.", "language": "en-GB"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(db.get_record("agents", profile["id"])["language"], "en-GB")
        self.assertEqual(self.client.delete(f"/api/knowledge/{doc['id']}").status_code, 204)
        self.assertEqual(db.get_record("agents", profile["id"])["knowledge_ids"], [])
        self.assertEqual(self.client.delete(f"/api/agents/{profile['id']}").status_code, 204)

    def test_validation_rejects_bad_documents_and_profiles(self):
        self.assertEqual(self.client.post("/api/agents", json={"name": "   "}).status_code, 422)
        self.assertEqual(self.client.post("/api/agents", json={"name": "Test", "knowledge_ids": ["missing"]}).status_code, 422)
        self.assertEqual(self.client.post("/api/knowledge", json={"title": "Notes", "content": "x" * 12001}).status_code, 422)
        self.assertEqual(self.client.get("/api/calls/absent").status_code, 404)

    def test_knowledge_retrieval_is_bounded_and_prioritizes_relevant_passages(self):
        notes = "General property information. " * 300 + " Budget parking school Jubilee Hills. " * 30
        context = relevant_context(notes, "What about parking near the school in Jubilee Hills?")
        self.assertLessEqual(len(context), 4500)
        self.assertIn("Jubilee Hills", context)

    def test_deleted_defaults_do_not_reappear_on_restart(self):
        for agent in self.client.get("/api/agents").json():
            self.client.delete(f"/api/agents/{agent['id']}")
        db.initialize()
        self.assertEqual(db.list_records("agents"), [])

    def test_readiness_never_exposes_keys(self):
        with patch.object(settings, "twilio_api_secret", "private-secret-test"):
            result = self.client.get("/api/settings")
            self.assertEqual(result.status_code, 200)
            self.assertNotIn("private-secret-test", result.text)
            self.assertEqual(len(result.json()["checks"]), 4)

    def test_twiml_profile_snapshot_and_one_active_call(self):
        doc = self.client.post("/api/knowledge", json={"title": "Listing", "content": "Price: 92 lakh."}).json()
        agent = self.client.post("/api/agents", json={"name": "Test", "language": "en-GB", "instructions": "Check budget", "knowledge_ids": [doc["id"]]}).json()
        with patch.object(settings, "public_base_url", "demo.example.com"), patch.object(settings, "twilio_phone_number", "+15550001111"):
            response = self.client.post("/twiml/voice", data={"CallId": "call-one", "PhoneNumber": "+919876543210", "AgentId": agent["id"]})
            self.assertIn('track="both_tracks"', response.text)
            self.assertIn("<Number", response.text)
            self.assertIn('answerOnBridge="true"', response.text)
            self.assertIn('/twiml/stream-status?', response.text)
            session = session_manager.get("call-one")
            self.prewarm.assert_called_once_with(session)
            self.assertEqual(session.profile["language"], "en-GB")
            self.assertIn("92 lakh", _build_user_prompt(session))
            self.assertIn("Check budget", _build_user_prompt(session))
            denied = self.client.post("/twiml/voice", data={"CallId": "call-two", "PhoneNumber": "+919876543210"})
            self.assertNotIn("<Dial", denied.text)
            self.assertEqual(session_manager.get("call-two").status, CallStatus.FAILED)

    def test_invalid_phone_never_dials(self):
        response = self.client.post("/twiml/voice", data={"CallId": "bad-number", "PhoneNumber": "abc"})
        self.assertNotIn("<Dial", response.text)
        self.assertEqual(session_manager.get("bad-number").status, CallStatus.FAILED)

    def test_late_callback_does_not_regress_connected_call(self):
        session = CallSession("connected-call")
        session.set_status(CallStatus.CONNECTED)
        session_manager._sessions[session.call_id] = session
        self.client.post("/twiml/status?callId=connected-call", data={"CallStatus": "ringing"})
        self.assertEqual(session.status, CallStatus.CONNECTED)

    def test_speaker_separation_and_language(self):
        session = CallSession("track-test")
        agent = TrackTranscriber(session, Speaker.AGENT)
        customer = TrackTranscriber(session, Speaker.CUSTOMER)
        agent.on_results("What is your", True, False)
        agent.on_results("budget?", True, True)
        customer.on_results("Eighty five lakh.", True, True)
        self.assertEqual([t.speaker for t in session.turns], [Speaker.AGENT, Speaker.CUSTOMER])
        self.assertEqual(session.turns[0].text, "What is your budget?")
        self.assertEqual([t.seq for t in session.turns], [1, 2])
        self.assertIn("language=en-GB", DeepgramTrack(Speaker.CUSTOMER, customer, "en-GB")._url())

    def test_browser_reconnect_replays_confirmed_and_partial_transcript(self):
        session = CallSession("replay-call")
        session.status = CallStatus.CONNECTED
        session.append_final(TranscriptTurn(id="saved-turn", speaker=Speaker.AGENT,
                                           text="What is your budget?", is_final=True, seq=1, revision=2))
        session.interim[Speaker.CUSTOMER] = "Eighty five"
        session_manager._sessions[session.call_id] = session
        with self.client.websocket_connect("/ws/replay-call") as ws:
            self.assertEqual(ws.receive_json()["status"], "connected")
            final = ws.receive_json()["turn"]
            self.assertEqual(final["text"], "What is your budget?")
            self.assertEqual(final["revision"], 2)
            partial = ws.receive_json()["turn"]
            self.assertEqual(partial["text"], "Eighty five")
            self.assertFalse(partial["is_final"])

    def test_recognition_hints_are_saved_and_bounded(self):
        saved = self.client.post("/api/agents", json={"name": "Hint test", "keyterms": [" Jubilee Hills ", "RERA", "RERA"]}).json()
        self.assertEqual(saved["keyterms"], ["Jubilee Hills", "RERA"])
        self.assertEqual(self.client.post("/api/agents", json={"name": "Bad hints", "keyterms": ["x" * 41]}).status_code, 422)

    def test_completed_call_is_saved_once_with_summary(self):
        async def run():
            session = CallSession("saved-call")
            session.to_number = "+919876543210"
            session.profile = {"name": "Buyer coach"}
            session.set_status(CallStatus.CONNECTED)
            session.append_final(TranscriptTurn(id="turn", speaker=Speaker.CUSTOMER, text="Saturday works.", is_final=True, seq=1))
            summary = CallSummary(outcome="progressed", commitments=["Confirm Saturday viewing."])
            with patch("app.services.summary.generate_summary", AsyncMock(return_value=summary)) as generate, patch("app.services.lifecycle._drain", AsyncMock()):
                await teardown_call(session)
                await teardown_call(session)
                self.assertEqual(generate.await_count, 1)
            return summary
        asyncio.run(run())
        data = self.client.get("/api/calls/saved-call").json()
        self.assertEqual(data["summary"]["outcome"], "progressed")
        self.assertEqual(data["transcript"][0]["speaker"], "customer")
        self.assertEqual(len(self.client.get("/api/calls").json()), 1)
        self.assertNotIn("transcript", self.client.get("/api/calls").json()[0])

    def test_disk_failure_still_delivers_summary(self):
        async def run():
            session = CallSession("disk-failure")
            with patch("app.services.summary.generate_summary", AsyncMock(return_value=CallSummary())), patch("app.calls.save_call", side_effect=OSError("disk unavailable")), patch("app.services.lifecycle._drain", AsyncMock()):
                await teardown_call(session)
            events = []
            while not session.out_queue.empty():
                events.append(session.out_queue.get_nowait())
            self.assertTrue(any(event["type"] == "summary" for event in events))
            self.assertTrue(any(event["type"] == "notice" for event in events))
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
