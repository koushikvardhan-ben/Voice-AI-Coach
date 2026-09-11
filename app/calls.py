"""Persist finished calls, and expose honest local configuration readiness."""
import os
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app import db
from app.config import settings

router = APIRouter(prefix="/api", tags=["workspace"])


def save_call(session, summary):
    db.save_record("calls", {
        "id": session.call_id, "number": session.to_number,
        "agent_name": session.profile.get("name", "Sales coach"),
        "created_at": session.created_at,
        "duration": max(0, int((session.ended_at or time.time()) - (session.connected_at or time.time()))),
        "end_reason": session.end_reason,
        "diagnostics": session.diagnostics,
        "status": session.status.value,
        "transcript": [turn.model_dump(mode="json") for turn in session.turns],
        "summary": summary.model_dump(mode="json"),
        "recording_path": session.recording_path,
    })


@router.get("/calls")
def calls():
    return [{k: v for k, v in call.items() if k != "transcript"} for call in db.list_records("calls")]


@router.get("/calls/{call_id}")
def call_detail(call_id: str):
    call = db.get_record("calls", call_id)
    if not call:
        raise HTTPException(404, "Call not found.")
    return call


@router.get("/calls/{call_id}/recording")
def call_recording(call_id: str):
    call = db.get_record("calls", call_id)
    if not call:
        raise HTTPException(404, "Call not found.")
    path = call.get("recording_path")
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "No recording was saved for this call.")
    return FileResponse(path, media_type="audio/wav", filename=f"call-{call_id}.wav")


@router.get("/settings")
def readiness():
    required = ["twilio_account_sid", "twilio_api_key", "twilio_api_secret", "twilio_twiml_app_sid", "twilio_phone_number"]
    missing = [key.upper() for key in required if not getattr(settings, key)]
    checks = [
        {"name": "Twilio Voice", "configured": not missing, "detail": "Browser calling credentials present" if not missing else "Missing: " + ", ".join(missing)},
        {"name": "Deepgram", "configured": bool(settings.deepgram_api_key), "detail": f"{settings.deepgram_model} · two speaker streams"},
        {"name": "Groq", "configured": bool(settings.groq_api_key), "detail": settings.groq_model},
        {"name": "Public tunnel", "configured": bool(settings.public_host()), "detail": settings.public_host() or "Set PUBLIC_BASE_URL in .env"},
    ]
    return {"checks": checks, "ready": all(c["configured"] for c in checks), "language": settings.deepgram_language, "coach_interval": settings.coach_min_interval_seconds}
