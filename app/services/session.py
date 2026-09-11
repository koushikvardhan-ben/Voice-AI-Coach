"""In-memory per-call session state and the single-active-call registry.

This module is deliberately decoupled from Deepgram / Groq: it only holds
state, a bounded outbound event queue (with interim-drop backpressure), a task
registry, and small helpers. The end-to-end teardown orchestration lives in
``services/lifecycle.py``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import WebSocket

from app.config import settings
from app.models import (
    CallStatus,
    CoachState,
    Speaker,
    TranscriptTurn,
    status_event,
)
from app.services.recording import CallRecorder

OUT_QUEUE_MAXSIZE = 1000


def _is_interim_transcript(event: dict[str, Any]) -> bool:
    return event.get("type") == "transcript" and not event.get("turn", {}).get("is_final", False)


class CallSession:
    """Everything we know about one live call. Source of truth is in-memory."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self.status: CallStatus = CallStatus.IDLE
        self.to_number: str | None = None
        self.stream_sid: str | None = None
        self.parent_call_sid: str | None = None
        self.media_ws: WebSocket | None = None
        self.media_recovery: asyncio.Task | None = None
        self.media_cleanup = False
        self.media_recovery_attempts = 0
        # Once true, the call has streamed real audio at least once; a media
        # reconnect must resume transcription immediately, never re-gate on
        # the pre-answer hold below.
        self.audio_started = False
        # Stereo WAV recorder, fed the same telephony-confirmed audio as STT.
        self.recorder = CallRecorder() if settings.record_calls else None
        self.recording_path: str | None = None
        self.stt_tasks: list[asyncio.Task] = []
        self.teardown_task: asyncio.Task | None = None
        self.ended_at: float | None = None
        self.end_reason: str | None = None
        self.diagnostics: list[dict] = []
        self.stt_state: dict[str, dict] = {}
        self.created_at: float = time.time()
        self.connected_at: float | None = None
        self.profile: dict = {}
        self.knowledge_context: str = ""

        # Transcript: finals are canonical; interim is the live line per speaker.
        self.turns: list[TranscriptTurn] = []
        self.interim: dict[Speaker, str] = {}
        self._seq: int = 0

        # Coaching state / bookkeeping.
        self.running_summary: str = ""
        self.coach_state: CoachState | None = None
        self.last_coach_at: float = 0.0
        self.coach_dirty: bool = False
        self.coach_inflight: bool = False
        self.coach_revision: int = 0
        self.coach_retry_at: float = 0.0
        self.coach_status: dict | None = None
        self.debounce_task: asyncio.Task | None = None

        # Connections / plumbing.
        self.browser_ws: WebSocket | None = None
        self.browser_sender: asyncio.Task | None = None
        self.out_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=OUT_QUEUE_MAXSIZE)
        self.tasks: set[asyncio.Task] = set()

        # Deepgram track wrappers (set by the media handler; typed loosely to
        # avoid an import cycle). Duck-typed: .finish() awaitable.
        self.dg_agent: Any = None
        self.dg_customer: Any = None

        # Teardown guard.
        self._closing: bool = False
        self.summary_sent: bool = False

    # --- transcript helpers ---

    def diagnose(self, source: str, event: str, **details) -> None:
        self.diagnostics.append({"at": time.time(), "source": source, "event": event, **details})
        self.diagnostics = self.diagnostics[-100:]

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def append_final(self, turn: TranscriptTurn) -> None:
        self.turns.append(turn)
        self.interim.pop(turn.speaker, None)

    def recent_window(self, max_turns: int) -> list[TranscriptTurn]:
        return self.turns[-max_turns:]

    # --- outbound event queue (server -> browser) ---

    def push(self, event: dict[str, Any]) -> None:
        """Enqueue an event for the browser. Under pressure we sacrifice
        disposable interim transcript events, never finals/coach/summary/status."""
        try:
            self.out_queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass
        if _is_interim_transcript(event):
            return  # drop the incoming interim
        # Make room by dropping one queued item, then enqueue the important event.
        try:
            self.out_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            self.out_queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def set_status(self, status: CallStatus) -> None:
        if status == CallStatus.CONNECTED and self.connected_at is None:
            self.connected_at = time.time()
        self.status = status
        self.push(status_event(self.call_id, status))

    # --- task registry ---

    def track(self, task: asyncio.Task) -> asyncio.Task:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def cancel_tasks(self) -> None:
        tasks = [t for t in self.tasks if t is not asyncio.current_task()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- teardown guard ---

    def begin_closing(self) -> bool:
        """Return True the first time this is called; False on subsequent calls
        (so teardown runs exactly once across its several trigger sources)."""
        if self._closing:
            return False
        self._closing = True
        return True

    @property
    def closing(self) -> bool:
        return self._closing

    @property
    def is_active(self) -> bool:
        return self.status in (CallStatus.DIALING, CallStatus.RINGING, CallStatus.CONNECTED)


class SessionManager:
    """Registry of live calls. Prototype scope: one active call at a time."""

    def __init__(self) -> None:
        self._sessions: dict[str, CallSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, call_id: str) -> CallSession:
        """Return the session for ``call_id``, creating it if absent.

        The browser WS and the Twilio TwiML request race to be first; whichever
        arrives creates the session under the lock.
        """
        async with self._lock:
            session = self._sessions.get(call_id)
            if session is None:
                session = CallSession(call_id)
                self._sessions[call_id] = session
            return session

    def get(self, call_id: str) -> CallSession | None:
        return self._sessions.get(call_id)

    def has_active_call(self) -> bool:
        return any(s.is_active for s in self._sessions.values())

    def remove(self, call_id: str) -> None:
        self._sessions.pop(call_id, None)

    def all(self) -> list[CallSession]:
        return list(self._sessions.values())


# Single process-wide registry, imported by routes / ws handlers.
session_manager = SessionManager()
