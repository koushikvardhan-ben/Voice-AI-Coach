"""Thin, swappable LLM client. Groq today; the Protocol lets us swap providers.

All calls request a JSON object back (``response_format`` json_object) so the
coach and summary can parse structured output.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from groq import AsyncGroq, RateLimitError

from app.config import settings

log = logging.getLogger("llm")


class LLMError(Exception):
    pass


class LLMRateLimited(LLMError):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class LLMClient(Protocol):
    async def complete_json(
        self, system: str, user: str, max_tokens: int, temperature: float = 0.3
    ) -> dict[str, Any]: ...


class GroqLLM:
    def __init__(self) -> None:
        # The coaching scheduler owns retries/backoff; SDK retries otherwise hide
        # rate limits and keep an obsolete request alive for too long.
        self._client = AsyncGroq(api_key=settings.groq_api_key, timeout=10, max_retries=0)
        self.model = settings.groq_model

    async def complete_json(
        self, system: str, user: str, max_tokens: int, temperature: float = 0.3
    ) -> dict[str, Any]:
        try:
            options = {}
            if self.model.startswith("openai/gpt-oss-"):
                options["reasoning_effort"] = "low"
                # The completion budget includes reasoning as well as JSON. The
                # old 350-token cap could run out before producing an answer.
                max_tokens = max(max_tokens, 1024)
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=max_tokens,
                temperature=temperature,
                **options,
            )
        except RateLimitError as e:
            retry_after = None
            resp_obj = getattr(e, "response", None)
            if resp_obj is not None:
                ra = resp_obj.headers.get("retry-after")
                try:
                    retry_after = float(ra) if ra else None
                except ValueError:
                    retry_after = None
            raise LLMRateLimited(retry_after) from e
        except Exception as e:  # noqa: BLE001
            raise LLMError(str(e)) from e

        if not resp.choices or resp.choices[0].finish_reason == "length":
            raise LLMError("Model response exceeded its completion budget")
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise LLMError("Model returned an empty answer")
        try:
            data = json.loads(content)
            if not isinstance(data, dict):
                raise LLMError("Model response was not a JSON object")
            return data
        except json.JSONDecodeError as e:
            raise LLMError("Model returned invalid JSON") from e


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = GroqLLM()
    return _client
