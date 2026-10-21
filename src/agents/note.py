"""Internal Note Agent — drafts the helpdesk internal note.

Uses: gpt-4.1 (or configured OPENAI_MODEL / NOTE_LLM_PROVIDER).
System prompt: ~3K tokens (slim internal_note.md + note_format.md only).
  — process_rules.md removed: Safety Agent output covers those facts.

Chunk filtering: receives ALL chunk types (procedure, reference, known-issue,
handbook) since the note may need to cite any of them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import get_note_adapter
from ..llm import LLMAdapter
from ..retrieve import Hit
from ..schemas import ClassifierOutput, NoteOutput, SafetyOutput

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    """Load and interpolate once; cached for the process lifetime."""
    raw = (PROMPTS_DIR / "internal_note.md").read_text(encoding="utf-8")
    note_format = (PROMPTS_DIR / "note_format.md").read_text(encoding="utf-8")
    # process_rules intentionally NOT injected — saves ~8K tokens per call.
    return raw.replace("{NOTE_FORMAT}", note_format)


def _format_context(hits: list[Hit]) -> str:
    if not hits:
        return "(no relevant SOPs were retrieved)"
    parts: list[str] = []
    for i, h in enumerate(hits, start=1):
        meta = h.metadata or {}
        header = (
            f"### Source {i}: {h.title} — {h.heading}\n"
            f"(type={meta.get('type', '?')}, article_id={meta.get('article_id', '?')}, "
            f"source_url={meta.get('source_url', '')})"
        )
        parts.append(f"{header}\n\n{h.text.strip()}")
    return "\n\n---\n\n".join(parts)


def run_note(
    ticket: str,
    classification: ClassifierOutput,
    safety: SafetyOutput,
    hits: list[Hit],
    revision_feedback: str = "",
    *,
    adapter: LLMAdapter | None = None,
) -> NoteOutput:
    """Run the Internal Note Agent."""
    adapter = adapter or get_note_adapter()

    classifier_json = classification.model_dump_json(indent=2)
    safety_json = safety.model_dump_json(indent=2)
    retrieved = _format_context(hits)

    revision_block = ""
    if revision_feedback.strip():
        revision_block = (
            "# QA Revision Required\n\n"
            "<qa_feedback>\n"
            f"{revision_feedback.strip()}\n"
            "</qa_feedback>\n\n"
            "The previous internal note draft failed QA. Fix the issues listed above "
            "and re-generate the complete note.\n\n"
        )

    user = (
        "# Incoming ticket\n\n"
        f"{ticket.strip()}\n\n"
        f"{revision_block}"
        "# Classifier signals\n\n"
        f"```json\n{classifier_json}\n```\n\n"
        "# Safety analysis\n\n"
        f"```json\n{safety_json}\n```\n\n"
        "# Retrieved context\n\n"
        "<retrieved_context>\n"
        f"{retrieved}\n"
        "</retrieved_context>\n\n"
        "Produce the NoteOutput JSON now."
    )

    return adapter.parse(
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user},
        ],
        response_format=NoteOutput,
        temperature=0.1,
    )
