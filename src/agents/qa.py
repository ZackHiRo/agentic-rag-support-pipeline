"""QA Agent — validates all drafting outputs against the full rule set.

Uses: gpt-4.1 (or configured OPENAI_QA_MODEL / QA_LLM_PROVIDER).
System prompt: ~1.3K tokens (qa.md only).

The QA agent receives compact summaries of each output rather than the
full JSON blobs, to keep the user message token-efficient. The full JSON
is available via the per-agent expanders in the UI.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import get_qa_adapter
from ..llm import LLMAdapter
from ..retrieve import Hit
from ..schemas import (
    ClassifierOutput,
    NoteOutput,
    QAResult,
    ReplyOutput,
    SafetyOutput,
    StepsOutput,
)

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    return (PROMPTS_DIR / "qa.md").read_text(encoding="utf-8")


def _context_titles(hits: list[Hit]) -> str:
    """Compact citation reference list for the QA agent."""
    if not hits:
        return "(none)"
    return "\n".join(
        f"- {h.title} > {h.heading}  [article_id={(h.metadata or {}).get('article_id', '?')}]"
        for h in hits
    )


def run_qa(
    ticket: str,
    classification: ClassifierOutput,
    safety: SafetyOutput,
    note_out: NoteOutput,
    reply_out: ReplyOutput,
    steps_out: StepsOutput,
    hits: list[Hit],
    *,
    adapter: LLMAdapter | None = None,
) -> QAResult:
    """Run the QA Agent."""
    adapter = adapter or get_qa_adapter()

    user = (
        "# Incoming ticket\n\n"
        f"{ticket.strip()}\n\n"
        "# Classifier signals\n\n"
        f"```json\n{classification.model_dump_json(indent=2)}\n```\n\n"
        "# Safety analysis (ground truth for PII/escalation checks)\n\n"
        f"```json\n{safety.model_dump_json(indent=2)}\n```\n\n"
        "# Retrieved SOP articles (for citation verification)\n\n"
        f"{_context_titles(hits)}\n\n"
        "# Internal Note Agent output\n\n"
        f"```json\n{note_out.model_dump_json(indent=2)}\n```\n\n"
        "# Player Reply Agent output\n\n"
        f"```json\n{reply_out.model_dump_json(indent=2)}\n```\n\n"
        "# Next Steps Agent output\n\n"
        f"```json\n{steps_out.model_dump_json(indent=2)}\n```\n\n"
        "Evaluate all outputs against the full checklist and produce the QAResult JSON now."
    )

    try:
        return adapter.parse(
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": user},
            ],
            response_format=QAResult,
            temperature=0.0,
        )
    except Exception:
        return QAResult(
            overall_score=0.0,
            passed=False,
            qa_agent_notes="[QA Agent failed — manual review required]",
        )
