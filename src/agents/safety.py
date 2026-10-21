"""Safety Agent — PII detection, escalation, threat classification.

Uses: gpt-4.1-mini (or configured OPENAI_SAFETY_MODEL).
System prompt: ~875 tokens (safety.md only — no heavy handbooks).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import get_safety_adapter
from ..llm import LLMAdapter
from ..schemas import ClassifierOutput, SafetyOutput

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    """Load once; cached for the process lifetime."""
    return (PROMPTS_DIR / "safety.md").read_text(encoding="utf-8")


def run_safety(
    ticket: str,
    classification: ClassifierOutput,
    *,
    adapter: LLMAdapter | None = None,
) -> SafetyOutput:
    """Run the Safety Agent.

    Parameters
    ----------
    ticket:
        Composed ticket text (vision transcription prepended if applicable).
    classification:
        Output from the Classifier Agent — provides language/urgency/flags
        as extra context without re-deriving them.
    adapter:
        LLMAdapter to use. Defaults to the global safety adapter from config.
    """
    adapter = adapter or get_safety_adapter()

    classifier_json = classification.model_dump_json(indent=2)
    user = (
        "# Incoming ticket\n\n"
        f"{ticket.strip()}\n\n"
        "# Classifier signals (for context only)\n\n"
        f"```json\n{classifier_json}\n```\n\n"
        "Produce the SafetyOutput JSON now."
    )

    try:
        return adapter.parse(
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": user},
            ],
            response_format=SafetyOutput,
            temperature=0.0,
        )
    except Exception:
        return SafetyOutput(
            escalation_flag=False,
            safety_notes="[Safety Agent failed — manual review required]",
        )
