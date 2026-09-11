"""Outbound browser call: fork both audio tracks and report customer-leg status."""
import re
from urllib.parse import urlencode
from fastapi import APIRouter, Request, Response
from twilio.twiml.voice_response import Dial, Start, Stream, VoiceResponse
from app import db
from app.config import settings
from app.models import CallStatus, notice_event
from app.services.session import session_manager
from app.services.lifecycle import schedule_teardown
from app.services.telephony import stream_callback_url, schedule_media_recovery

router = APIRouter()
_STATUS_MAP = {"initiated": CallStatus.DIALING, "ringing": CallStatus.RINGING,
               "in-progress": CallStatus.CONNECTED, "answered": CallStatus.CONNECTED,
               "completed": CallStatus.ENDED, "busy": CallStatus.FAILED,
               "no-answer": CallStatus.FAILED, "failed": CallStatus.FAILED,
               "canceled": CallStatus.ENDED}


@router.post("/twiml/voice")
async def twiml_voice(request: Request):
    form = await request.form()
    call_id = str(form.get("CallId") or "").strip()
    to = str(form.get("PhoneNumber") or form.get("To") or "").strip()
    vr = VoiceResponse()
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", call_id):
        vr.say("Missing or invalid call identifier.")
        vr.hangup()
        return Response(str(vr), media_type="application/xml")
    session = await session_manager.get_or_create(call_id)
    error = None
    if not re.fullmatch(r"\+[1-9]\d{7,14}", to):
        error = "Enter a valid phone number with country code."
    elif not settings.public_host() or not settings.twilio_phone_number:
        error = "Configure the public tunnel and Twilio caller ID first."
    elif any(other.is_active and other.call_id != call_id for other in session_manager.all()):
        error = "Another call is already active. End it before dialing again."
    profile_id = str(form.get("AgentId") or "")
    profile = db.get_record("agents", profile_id) if profile_id else None
    if profile_id and not profile:
        error = "This coaching profile no longer exists. Select another profile."
    if error:
        session.push(notice_event("error", error))
        session.set_status(CallStatus.FAILED)
        vr.say(error)
        vr.hangup()
        return Response(str(vr), media_type="application/xml")
    # No await between the active-call check and reservation: atomic in this worker.
    session.to_number = to
    session.parent_call_sid = str(form.get("CallSid") or "") or None
    session.profile = profile or {}
    notes = [db.get_record("knowledge", key) for key in session.profile.get("knowledge_ids", [])]
    session.knowledge_context = "\n\n".join(f"{note['title']}:\n{note['content']}" for note in notes if note)
    session.set_status(CallStatus.DIALING)
    from app.ws.media import start_transcription
    start_transcription(session)
    start = Start()
    stream = Stream(url=settings.wss_media_url(call_id), track="both_tracks",
                    status_callback=stream_callback_url(call_id), status_callback_method="POST")
    stream.parameter(name="callId", value=call_id)
    start.append(stream)
    vr.append(start)
    callback = f"https://{settings.public_host()}/twiml/status?{urlencode({'callId': call_id})}"
    dial = Dial(caller_id=settings.twilio_phone_number, answer_on_bridge=True)
    dial.number(to, status_callback=callback, status_callback_method="POST",
                status_callback_event="initiated ringing answered completed")
    vr.append(dial)
    return Response(str(vr), media_type="application/xml")


@router.post("/twiml/status")
async def twiml_status(request: Request):
    form = await request.form()
    call_id = request.query_params.get("callId", "")
    session = session_manager.get(call_id)
    raw = str(form.get("CallStatus") or "")
    status = _STATUS_MAP.get(raw)
    if session and status and not session.closing and not session.teardown_task:
        session.diagnose("twilio", raw, error_code=str(form.get("ErrorCode") or ""))
        # Late, out-of-order callbacks must not regress an answered call.
        if session.status == CallStatus.CONNECTED and status in (CallStatus.DIALING, CallStatus.RINGING):
            return Response(status_code=204)
        session.set_status(status)
        if status in (CallStatus.ENDED, CallStatus.FAILED):
            schedule_teardown(session, reason=raw)
    return Response(status_code=204)


@router.post("/twiml/stream-status")
async def twiml_stream_status(request: Request):
    form = await request.form()
    session = session_manager.get(request.query_params.get("callId", ""))
    if session and not session.closing:
        event = str(form.get("StreamEvent") or "")
        # Bound provider diagnostics; never record the request's credentials/audio.
        session.diagnose("twilio_stream", event, detail=str(form.get("StreamError") or "")[:300])
        if event in {"stream-error", "stream-stopped"}:
            schedule_media_recovery(session)
    return Response(status_code=204)
