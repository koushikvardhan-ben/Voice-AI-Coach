"""Recover the audio fork without changing or hanging up the telephone call."""
import asyncio
import logging
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.models import notice_event
from app.services.lifecycle import schedule_teardown

log = logging.getLogger("telephony")
TERMINAL = {"completed", "busy", "no-answer", "failed", "canceled"}


def stream_callback_url(call_id: str) -> str:
    return f"https://{settings.public_host()}/twiml/stream-status?{urlencode({'callId': call_id})}"


def schedule_media_recovery(session) -> None:
    if session.closing or session.teardown_task or session.media_cleanup or session.media_ws is not None:
        return
    if session.media_recovery and not session.media_recovery.done():
        return
    if session.media_recovery_attempts >= 3:
        return
    session.media_recovery = session.track(asyncio.create_task(_recover_media(session)))


async def _recover_media(session) -> None:
    # Read the parent leg before restarting only its unidirectional audio fork.
    # Never rewrite Call TwiML or send a call status update: those can end a bridge.
    if not session.parent_call_sid or not settings.twilio_auth_token:
        session.push(notice_event("warn", "The audio stream stopped. The phone call can continue, but automatic transcript recovery needs TWILIO_AUTH_TOKEN."))
        return
    base = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Calls/{session.parent_call_sid}"
    async with httpx.AsyncClient(auth=(settings.twilio_account_sid, settings.twilio_auth_token), timeout=5) as client:
        for attempt in range(3 - session.media_recovery_attempts):
            await asyncio.sleep(.5 * 2 ** attempt)
            if session.closing or session.teardown_task or session.media_ws is not None:
                return
            session.media_recovery_attempts += 1
            try:
                response = await client.get(base + ".json")
                response.raise_for_status()
                status = response.json().get("status")
                if status in TERMINAL:
                    schedule_teardown(session, status)
                    return
                if session.closing or session.teardown_task or session.media_ws is not None:
                    return
                response = await client.post(base + "/Streams.json", data={
                    "Url": settings.wss_media_url(session.call_id), "Track": "both_tracks",
                    "StatusCallback": stream_callback_url(session.call_id), "StatusCallbackMethod": "POST",
                })
                response.raise_for_status()
                stream_sid = response.json().get("sid")
                session.diagnose("media", "restart_requested", attempt=attempt + 1)
                # Wait for the replacement WebSocket; do not create duplicate forks.
                for _ in range(25):
                    await asyncio.sleep(.2)
                    if session.closing or session.teardown_task or session.media_ws is not None:
                        return
                if stream_sid:
                    stopped = await client.post(base + f"/Streams/{stream_sid}.json", data={"Status": "stopped"})
                    stopped.raise_for_status()
            except (httpx.HTTPError, ValueError) as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                session.diagnose("media", "restart_failed", http_status=code, error=type(exc).__name__)
                log.warning("media recovery call_id=%s attempt=%d error=%s status=%s", session.call_id, attempt + 1, type(exc).__name__, code)
                if code in (400, 401, 403, 404):
                    break
    if not session.closing and session.media_ws is None:
        session.push(notice_event("warn", "Transcription could not reconnect. The phone call is still under your control. Check the backend/tunnel connection."))
