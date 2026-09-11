"""Twilio Voice Access Token endpoint for the browser softphone.

The browser fetches this JWT to register a ``Twilio.Device``. It is signed with
an API Key/Secret (not the account auth token) and scoped to our TwiML App so
outbound calls route through ``/twiml/voice``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant

from app.config import settings

router = APIRouter()

IDENTITY = "agent"


@router.get("/api/token")
def get_token() -> dict[str, str]:
    missing = [
        name
        for name, value in {
            "TWILIO_ACCOUNT_SID": settings.twilio_account_sid,
            "TWILIO_API_KEY": settings.twilio_api_key,
            "TWILIO_API_SECRET": settings.twilio_api_secret,
            "TWILIO_TWIML_APP_SID": settings.twilio_twiml_app_sid,
        }.items()
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Twilio not configured. Missing in .env: {', '.join(missing)}",
        )

    token = AccessToken(
        settings.twilio_account_sid,
        settings.twilio_api_key,
        settings.twilio_api_secret,
        identity=IDENTITY,
        ttl=3600,
    )
    token.add_grant(
        VoiceGrant(
            outgoing_application_sid=settings.twilio_twiml_app_sid,
            incoming_allow=False,
        )
    )
    jwt = token.to_jwt()
    if isinstance(jwt, bytes):  # older twilio returns bytes
        jwt = jwt.decode()
    return {"token": jwt, "identity": IDENTITY}
