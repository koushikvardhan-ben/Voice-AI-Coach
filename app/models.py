"""Pydantic models for call state + the browser WebSocket message schema.

Only finals live in the canonical transcript; interim results are visual-only.
The browser WS speaks JSON objects with a ``type`` discriminator (see the
``*_event`` builders at the bottom).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class CallStatus(str, Enum):
    IDLE = "idle"
    DIALING = "dialing"
    RINGING = "ringing"
    CONNECTED = "connected"
    ENDED = "ended"
    FAILED = "failed"


class Speaker(str, Enum):
    AGENT = "agent"        # inbound track on the parent leg (the browser softphone)
    CUSTOMER = "customer"  # outbound track (the dialed buyer / seller)


class TranscriptTurn(BaseModel):
    id: str
    speaker: Speaker
    text: str
    is_final: bool
    seq: int
    revision: int = 0
    ts: float = Field(default_factory=time.time)


class CoachState(BaseModel):
    """The live coaching panel. ``running_summary`` is model-maintained context
    and is kept server-side (not shown to the agent)."""

    stage: Literal["opening", "discovery", "objection_handling", "closing", "other"] = "opening"
    customer_role: Literal["buyer", "seller", "unknown"] = "unknown"
    sentiment: Literal["cold", "neutral", "warm", "hot", "frustrated"] = "neutral"
    temperature: int = Field(default=50, ge=0, le=100)
    next_move: str = ""
    rationale: str = ""
    running_summary: str = ""
    updated_at: float = Field(default_factory=time.time)
    based_on_revision: int = 0


class CallSummary(BaseModel):
    key_points: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    outcome: Literal["progressed", "stalled", "lost", "unclear"] = "unclear"


# --- Browser WebSocket event builders (server -> browser) ---


def status_event(call_id: str, status: CallStatus | str) -> dict[str, Any]:
    return {
        "type": "status",
        "callId": call_id,
        "status": status.value if isinstance(status, CallStatus) else status,
        "ts": time.time(),
    }


def transcript_event(turn: TranscriptTurn) -> dict[str, Any]:
    return {"type": "transcript", "turn": turn.model_dump(mode="json")}


def coach_event(coach: CoachState) -> dict[str, Any]:
    # running_summary is context for the model, not for the agent's screen.
    return {"type": "coach", "coach": coach.model_dump(mode="json", exclude={"running_summary"})}


def summary_event(summary: CallSummary) -> dict[str, Any]:
    return {"type": "summary", "summary": summary.model_dump(mode="json")}


def notice_event(level: str, message: str) -> dict[str, Any]:
    return {"type": "notice", "level": level, "message": message, "ts": time.time()}
