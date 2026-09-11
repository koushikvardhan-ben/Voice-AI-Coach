"""End-of-call teardown orchestration.

Called only when telephony confirms the call ended. A media socket drop is
not a hangup. ``begin_closing()`` makes finalization run exactly once.
Order matters: finalize the summary and flush it to the browser BEFORE we cancel
tasks and close the browser socket.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.models import CallStatus, summary_event
from app.services.session import CallSession, session_manager

log = logging.getLogger("lifecycle")

_TERMINAL_FAIL = {"busy", "no-answer", "failed"}


def schedule_teardown(session: CallSession, reason: str) -> None:
    """Acknowledge Twilio callbacks without waiting for STT or the summary."""
    if session.closing or session.teardown_task is not None:
        return
    session.ended_at = time.time()
    session.end_reason = reason
    session.set_status(CallStatus.FAILED if reason in _TERMINAL_FAIL else CallStatus.ENDED)
    session.teardown_task = session.track(asyncio.create_task(teardown_call(session, reason)))


async def teardown_call(session: CallSession, reason: str = "") -> None:
    if not session.begin_closing():
        return
    session.ended_at = session.ended_at or time.time()
    session.end_reason = session.end_reason or reason
    session.diagnose("lifecycle", "ended", reason=session.end_reason)
    log.info("teardown call_id=%s reason=%s", session.call_id, reason)

    # 1. Stop any pending coaching debounce so it can't fire mid-teardown.
    if session.debounce_task is not None and not session.debounce_task.done():
        session.debounce_task.cancel()

    # 2. Final status.
    session.set_status(CallStatus.FAILED if reason in _TERMINAL_FAIL else CallStatus.ENDED)

    # 3. Flush + close both Deepgram sockets.
    await asyncio.gather(*(
        asyncio.wait_for(dg.finish(), timeout=4.0)
        for dg in (session.dg_agent, session.dg_customer) if dg is not None
    ), return_exceptions=True)

    # 3b. Write the stereo call recording (best-effort; never blocks the summary).
    try:
        from app.services.recording import save_recording
        session.recording_path = save_recording(session)
    except Exception:
        log.exception("recording failed call_id=%s", session.call_id)

    # 4. Post-call summary (the last LLM call).
    if not session.summary_sent:
        try:
            from app.services.summary import generate_summary

            try:
                summary = await asyncio.wait_for(generate_summary(session), timeout=20)
            except TimeoutError:
                from app.models import CallSummary
                summary = CallSummary(outcome="unclear", key_points=["Summary unavailable: the provider timed out. The confirmed transcript is saved."])
            from app.calls import save_call
            try:
                save_call(session, summary)
            except Exception:
                log.exception("Could not persist call_id=%s", session.call_id)
                from app.models import notice_event
                session.push(notice_event("error", "This call could not be saved to history. Export the transcript and summary before leaving."))
            session.push(summary_event(summary))
            session.summary_sent = True
        except Exception:  # noqa: BLE001
            log.exception("summary failed call_id=%s", session.call_id)

    # 5. Let the browser sender flush queued events (esp. the summary).
    await _drain(session, timeout=5.0)

    # 6. Close browser socket, cancel remaining tasks, drop the session.
    if session.media_ws is not None:
        try:
            await session.media_ws.close()
        except Exception:
            pass
    if session.browser_ws is not None:
        try:
            await session.browser_ws.close()
        except Exception:  # noqa: BLE001
            pass
    await session.cancel_tasks()
    session_manager.remove(session.call_id)
    log.info("teardown complete call_id=%s", session.call_id)


async def _drain(session: CallSession, timeout: float) -> None:
    if session.browser_ws is None:
        return
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not session.out_queue.empty() and loop.time() < deadline:
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.1)  # a beat for the in-flight send to complete
