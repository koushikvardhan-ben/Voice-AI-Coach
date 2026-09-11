"""Browser-facing WebSocket: pushes status / transcript / coach / summary events.

The browser opens ``/ws/{callId}`` as soon as the agent clicks Dial (before the
Twilio call starts), so this handler usually creates the session. A single
sender task drains ``session.out_queue`` to avoid interleaved writes.
"""

from __future__ import annotations

import asyncio
import logging
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models import CallStatus, coach_event, status_event, transcript_event, TranscriptTurn
from app.services.session import CallSession, session_manager
from app.services.lifecycle import schedule_teardown

router = APIRouter()
log = logging.getLogger("browser")


async def _send_loop(session: CallSession, ws: WebSocket) -> None:
    try:
        while True:
            event = await session.out_queue.get()
            await ws.send_json(event)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - socket closed / send failed
        pass


@router.websocket("/ws/{call_id}")
async def browser_ws(ws: WebSocket, call_id: str) -> None:
    await ws.accept()
    session = await session_manager.get_or_create(call_id)
    previous_ws = session.browser_ws
    session.browser_ws = ws
    if session.browser_sender is not None:
        session.browser_sender.cancel()
        await asyncio.gather(session.browser_sender, return_exceptions=True)
    if previous_ws is not None and previous_ws is not ws:
        try:
            await previous_ws.close()
        except Exception:
            pass
    session.browser_ws = ws
    log.info("browser ws connected call_id=%s", call_id)

    # Prime the client with current state (covers late-connect / reconnect).
    # Skip the initial IDLE so it can't clobber the client's local "dialing".
    if session.status != CallStatus.IDLE:
        await ws.send_json(status_event(call_id, session.status))
    # Replay confirmed state with revisions; old queued versions cannot replace
    # newer snapshots in the browser. Drop disposable stale partial updates.
    queued = []
    while not session.out_queue.empty():
        event = session.out_queue.get_nowait()
        if event.get("type") != "transcript" or event.get("turn", {}).get("is_final"):
            queued.append(event)
    for event in queued:
        session.out_queue.put_nowait(event)
    for turn in list(session.turns):
        await ws.send_json(transcript_event(turn))
    for speaker, text in list(session.interim.items()):
        await ws.send_json(transcript_event(TranscriptTurn(
            id=f"interim-{speaker.value}", speaker=speaker, text=text, is_final=False, seq=0)))
    if session.coach_state is not None:
        await ws.send_json(coach_event(session.coach_state))
    if session.coach_status is not None:
        await ws.send_json(session.coach_status)
    for event in session.stt_state.values():
        await ws.send_json(event)

    send_task = asyncio.create_task(_send_loop(session, ws))
    session.browser_sender = send_task
    session.track(send_task)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                event = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(event, dict) or session.browser_ws is not ws:
                continue
            if event.get("type") == "sdk_event" and event.get("event") in {
                "disconnect", "cancel", "error", "reconnecting", "reconnected", "local_hangup", "warning"
            }:
                name = event["event"]
                session.diagnose("browser_sdk", name, code=str(event.get("code") or "")[:40])
                # A WebSocket closing is NOT a hangup. A Twilio SDK closed-call
                # event is an authoritative browser-leg end, including when the
                # provider status callback is unavailable.
                if name in {"disconnect", "cancel"} or (name == "error" and event.get("closed") is True):
                    schedule_teardown(session, "browser_" + name)
    except WebSocketDisconnect:
        log.info("browser ws disconnected call_id=%s", call_id)
    finally:
        send_task.cancel()
        if session.browser_ws is ws:
            session.browser_ws = None
            if session.status == CallStatus.IDLE and not session.stream_sid:
                session_manager.remove(call_id)
