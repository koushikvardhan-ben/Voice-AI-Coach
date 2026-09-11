"""Application settings, loaded from environment / .env file.

All secrets (Twilio, Deepgram, Groq) live in .env and are never committed.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Twilio ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""          # read call state / restart an interrupted audio fork
    twilio_api_key: str = ""             # API Key SID (NOT the account SID)
    twilio_api_secret: str = ""
    twilio_twiml_app_sid: str = ""
    twilio_phone_number: str = ""        # trial number, used as <Dial callerId>

    # --- Deepgram (streaming STT) ---
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    # en-IN by default; switch to "multi" for heavy Hindi/English (Hinglish) code-switching.
    deepgram_language: str = "en-IN"
    stt_endpointing_ms: int = Field(default=200, ge=100, le=1000)
    stt_audio_buffer_seconds: float = Field(default=2.0, ge=.5, le=5)
    # Keep words flowing instead of waiting for formatted dates/phone numbers.
    stt_smart_format: bool = False

    # --- Groq (coaching + summary LLM) ---
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # --- Call recording (stereo WAV per call, agent left / customer right) ---
    record_calls: bool = True
    recordings_dir: str = "data/recordings"

    # --- Public tunnel (ngrok) ---
    # Host only, e.g. "abc123.ngrok-free.app" (scheme is added where needed).
    public_base_url: str = ""

    # --- CORS (frontend origins), comma-separated ---
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Coaching economy knobs (keep Groq under free-tier limits) ---
    coach_debounce_seconds: float = Field(default=3.0, ge=0, le=5)
    coach_min_interval_seconds: float = Field(default=12.0, ge=.1, le=120)
    coach_timeout_seconds: float = Field(default=8.0, ge=.05, le=30)
    coach_window_turns: int = 12
    coach_max_tokens: int = 350

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def public_host(self) -> str:
        """Return the public host with any scheme / trailing slash stripped."""
        host = self.public_base_url.strip()
        for prefix in ("https://", "http://", "wss://", "ws://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
                break
        return host.rstrip("/")

    def wss_media_url(self, call_id: str) -> str:
        """The wss:// URL Twilio should open for Media Streams on this call.

        Must be the public ngrok host (never localhost) and must use wss://.
        """
        return f"wss://{self.public_host()}/media/{call_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
