"""Post-call structured summary, generated once at teardown via Groq."""

from __future__ import annotations

import logging

from app.models import CallSummary, Speaker
from app.prompts.summary_system import SUMMARY_SYSTEM_PROMPT
from app.services.llm import LLMError, LLMRateLimited, get_llm
from app.services.session import CallSession

log = logging.getLogger("summary")

_VALID_OUTCOMES = {"progressed", "stalled", "lost", "unclear"}


async def generate_summary(session: CallSession) -> CallSummary:
    finals = session.turns
    if not finals:
        return CallSummary(
            outcome="unclear",
            key_points=["No conversation was transcribed."],
        )

    lines = [
        f"{'AGENT' if t.speaker is Speaker.AGENT else 'CUSTOMER'}: {t.text}"
        for t in finals
    ]
    user = "Full call transcript follows. Produce the post-call summary JSON.\n\n" + "\n".join(lines)

    try:
        data = await get_llm().complete_json(
            SUMMARY_SYSTEM_PROMPT, user, max_tokens=700, temperature=0.2
        )
    except (LLMError, LLMRateLimited) as e:
        log.warning("summary generation failed: %s", e)
        return CallSummary(outcome="unclear", key_points=["Summary unavailable (LLM error)."])

    try:
        return CallSummary.model_validate(data)
    except Exception:  # noqa: BLE001 - salvage what we can
        log.warning("summary JSON failed validation: %s", data)

        def _strlist(value) -> list[str]:
            if not isinstance(value, list):
                return []
            return [str(x) for x in value][:6]

        outcome = data.get("outcome")
        return CallSummary(
            key_points=_strlist(data.get("key_points")),
            objections=_strlist(data.get("objections")),
            commitments=_strlist(data.get("commitments")),
            next_steps=_strlist(data.get("next_steps")),
            outcome=outcome if outcome in _VALID_OUTCOMES else "unclear",
        )
