"""Twilio Media Streams receiver.

Twilio opens this socket (from the ``<Start><Stream>`` in our TwiML) and pushes
base64 mu-law/8k audio for BOTH call legs. On the parent leg ``inbound`` = the
agent (browser) and ``outbound`` = the customer, which is our speaker labelling.
Each track is forwarded to its own Deepgram stream.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models import CallStatus, Speaker, notice_event
from app.services import coach
from app.services.deepgram_client import DeepgramTrack
from app.services.telephony import schedule_media_recovery
from app.services.session import session_manager
from app.services.transcript import TrackTranscriber

router = APIRouter()
log = logging.getLogger("media")

# Central speaker mapping — flip here if a Twilio account labels tracks the other way.
TRACK_TO_SPEAKER: dict[str, Speaker] = {
    "inbound": Speaker.AGENT,
    "outbound": Speaker.CUSTOMER,
}

KEEPALIVE_INTERVAL = 6.0
# Don't feed ringback / silence / the trial greeting into Deepgram before the
# callee answers: pre-answer audio backs up the stream and makes the first real
# words lag by seconds. Start on the telephony-confirmed answer, or fall back to
# this bound so a lost "answered" callback still starts transcription promptly.
# The hold applies only to the very first connect of a call (see audio_started);
# a mid-call media reconnect always resumes immediately.
PREANSWER_FALLBACK_SECONDS = 8.0


async def _keepalive_loop(tracks) -> None:
    while True:
        await asyncio.sleep(KEEPALIVE_INTERVAL)
        await asyncio.gather(*(track.keep_alive() for track in tracks), return_exceptions=True)


def start_transcription(session) -> None:
    """Preconnect during dialing; the media handler reuses these same tracks."""
    if session.dg_agent is not None or session.closing:
        return

    def on_final(turn) -> None:
        if not session.closing:
            coach.schedule_coaching(session)

    tracks = [DeepgramTrack(speaker, TrackTranscriber(session, speaker, on_final=on_final),
                           session.profile.get("language"), session.profile.get("keyterms"))
              for speaker in (Speaker.AGENT, Speaker.CUSTOMER)]
    session.dg_agent, session.dg_customer = tracks
    session.stt_tasks = [session.track(asyncio.create_task(track.run())) for track in tracks]
    session.stt_tasks.append(session.track(asyncio.create_task(_keepalive_loop(tracks))))


@router.websocket("/media/{call_id}")
async def media_ws(ws: WebSocket, call_id: str) -> None:
    await ws.accept()
    session = session_manager.get(call_id)
    # A late socket must not resurrect an ended call or replace a healthy stream.
    if session is None or session.closing or session.teardown_task or session.media_cleanup or session.media_ws is not None:
        await ws.close(code=1008)
        return
    session.media_ws = ws
    log.info("media ws connected call_id=%s", call_id)
    start_transcription(session)
    tracks = (session.dg_agent, session.dg_customer)
    tasks = list(session.stt_tasks)
    close_reason = "socket_closed"
    # Hold audio out of Deepgram until the callee answers (see constant above).
    # A reconnect on an already-started call streams immediately.
    streaming = session.audio_started or session.status is CallStatus.CONNECTED
    first_media_at: float | None = None
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "media":
                media = msg.get("media", {})
                payload = media.get("payload")
                speaker = TRACK_TO_SPEAKER.get(media.get("track"))
                if not payload or speaker is None:
                    continue
                if not streaming:
                    now = time.monotonic()
                    if first_media_at is None:
                        first_media_at = now
                    if session.status is CallStatus.CONNECTED or now - first_media_at >= PREANSWER_FALLBACK_SECONDS:
                        streaming = True
                        session.audio_started = True
                    else:
                        continue
                audio = base64.b64decode(payload)
                if session.recorder is not None:
                    try:
                        ts = float(media.get("timestamp") or 0.0)
                    except (TypeError, ValueError):
                        ts = 0.0
                    session.recorder.add(speaker, ts, audio)
                if speaker is Speaker.AGENT:
                    await tracks[0].send(audio)
                else:
                    await tracks[1].send(audio)

            elif event == "start":
                start = msg.get("start", {})
                session.stream_sid = start.get("streamSid") or msg.get("streamSid")
                session.parent_call_sid = session.parent_call_sid or start.get("callSid")
                session.media_recovery_attempts = 0
                # A reconnect opens a fresh stream whose media clock restarts at 0.
                if session.recorder is not None:
                    session.recorder.new_stream()
                session.diagnose("media", "started", stream_sid=session.stream_sid)
                log.info(
                    "media start call_id=%s stream_sid=%s tracks=%s",
                    call_id, session.stream_sid, start.get("tracks"),
                )

            elif event == "stop":
                close_reason = "stream_stop"
                log.info("media stop call_id=%s", call_id)
                break

            # "connected" / "mark" / "dtmf" -> ignored
    except WebSocketDisconnect as exc:
        close_reason = f"websocket_{exc.code}"
        log.info("media ws disconnected call_id=%s code=%s", call_id, exc.code)
    except Exception:  # noqa: BLE001
        close_reason = "receiver_error"
        log.exception("media ws error call_id=%s", call_id)
    finally:
        session.diagnose("media", close_reason)
        session.media_cleanup = True
        if session.media_ws is ws:
            session.media_ws = None
        # Media Streams is an audio fork, not the telephone connection. Only a
        # confirmed telephony end may finalize the call and generate its summary.
        if not session.closing and not session.teardown_task:
            session.push(notice_event("warn", "Transcription audio disconnected; trying to restore it. This does not hang up your phone call."))
            await asyncio.gather(*(asyncio.wait_for(track.finish(), 3) for track in tracks), return_exceptions=True)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if session.dg_agent is tracks[0]:
                session.dg_agent = session.dg_customer = None
                session.stt_tasks = []
            session.media_cleanup = False
            schedule_media_recovery(session)
        else:
            session.media_cleanup = False
