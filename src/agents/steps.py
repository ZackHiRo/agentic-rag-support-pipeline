"""Next Steps Agent — extracts ordered investigation/action steps from SOPs.

Uses: gpt-4.1-mini (or configured OPENAI_STEPS_MODEL / STEPS_LLM_PROVIDER).
System prompt: ~539 tokens (next_steps.md only — no heavy handbooks).

Chunk filtering: receives only procedure + known-issue chunks since steps
are extracted from operational SOPs, not handbooks or references.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import get_steps_adapter
from ..llm import LLMAdapter
from ..retrieve import Hit
from ..schemas import ClassifierOutput, SafetyOutput, StepsOutput

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"

# Chunk types that are useful for extracting investigation steps.
_STEPS_CHUNK_TYPES = {"procedure", "known-issue", "patch-note"}


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    return (PROMPTS_DIR / "next_steps.md").read_text(encoding="utf-8")


def _filter_hits(hits: list[Hit]) -> list[Hit]:
    """Keep only procedure / known-issue / patch-note chunks for steps.

    Falls back to all hits if filtering would leave nothing (e.g. only
    handbook chunks were retrieved for an unusual ticket).
    """
    filtered = [h for h in hits if (h.metadata or {}).get("type") in _STEPS_CHUNK_TYPES]
    return filtered if filtered else hits


def _format_context(hits: list[Hit]) -> str:
    if not hits:
        return "(no relevant SOPs were retrieved)"
    parts: list[str] = []
    for i, h in enumerate(hits, start=1):
        meta = h.metadata or {}
        header = (
            f"### Source {i}: {h.title} — {h.heading}\n"
            f"(type={meta.get('type', '?')}, article_id={meta.get('article_id', '?')})"
        )
        parts.append(f"{header}\n\n{h.text.strip()}")
    return "\n\n---\n\n".join(parts)


def run_steps(
    ticket: str,
    classification: ClassifierOutput,
    safety: SafetyOutput,
    hits: list[Hit],
    revision_feedback: str = "",
    *,
    adapter: LLMAdapter | None = None,
) -> StepsOutput:
    """Run the Next Steps Agent."""
    adapter = adapter or get_steps_adapter()

    filtered_hits = _filter_hits(hits)
    classifier_json = classification.model_dump_json(indent=2)
    safety_json = safety.model_dump_json(indent=2)
    retrieved = _format_context(filtered_hits)

    revision_block = ""
    if revision_feedback.strip():
        revision_block = (
            "# QA Revision Required\n\n"
            "<qa_feedback>\n"
            f"{revision_feedback.strip()}\n"
            "</qa_feedback>\n\n"
            "The previous next-steps draft failed QA. Fix the issues listed above "
            "and re-generate the complete steps list.\n\n"
        )

    user = (
        "# Incoming ticket\n\n"
        f"{ticket.strip()}\n\n"
        f"{revision_block}"
        "# Classifier signals\n\n"
        f"```json\n{classifier_json}\n```\n\n"
        "# Safety analysis\n\n"
        f"```json\n{safety_json}\n```\n\n"
        "# Retrieved context (procedure/known-issue chunks only)\n\n"
        "<retrieved_context>\n"
        f"{retrieved}\n"
        "</retrieved_context>\n\n"
        "Produce the StepsOutput JSON now."
    )

    return adapter.parse(
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user},
        ],
        response_format=StepsOutput,
        temperature=0.0,
    )
