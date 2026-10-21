"""Player Reply Agent — drafts the public reply to the player.

Uses: gpt-4.1 (or configured OPENAI_MODEL / REPLY_LLM_PROVIDER).
System prompt: ~4.7K tokens (player_reply.md + tone_rules.md only).
  — note_format.md and process_rules.md NOT included.

Chunk filtering: prefers procedure + handbook chunks (most tone-relevant).
All chunk types are still passed; the agent's prompt focuses it on player-
facing content.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import get_reply_adapter
from ..llm import LLMAdapter
from ..retrieve import Hit
from ..schemas import ClassifierOutput, ReplyOutput, SafetyOutput

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"


@lru_cache(maxsize=1)
def _system_prompt() -> str:
    """Load and interpolate once; cached for the process lifetime."""
    raw = (PROMPTS_DIR / "player_reply.md").read_text(encoding="utf-8")
    tone_rules = (PROMPTS_DIR / "tone_rules.md").read_text(encoding="utf-8")
    return raw.replace("{TONE_RULES}", tone_rules)


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


def _guidance_block(guidance: str) -> str:
    g = guidance.strip()
    if not g:
        return ""
    return (
        "# Agent guidance (from the human reviewer)\n\n"
        "<agent_guidance>\n"
        f"{g}\n"
        "</agent_guidance>\n\n"
    )


def run_reply(
    ticket: str,
    classification: ClassifierOutput,
    safety: SafetyOutput,
    hits: list[Hit],
    guidance: str = "",
    revision_feedback: str = "",
    *,
    adapter: LLMAdapter | None = None,
) -> ReplyOutput:
    """Run the Player Reply Agent."""
    adapter = adapter or get_reply_adapter()

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
            "The previous player reply draft failed QA. Fix the issues listed above "
            "and re-generate the complete reply.\n\n"
        )

    user = (
        "# Incoming ticket\n\n"
        f"{ticket.strip()}\n\n"
        f"{revision_block}"
        f"{_guidance_block(guidance)}"
        "# Classifier signals\n\n"
        f"```json\n{classifier_json}\n```\n\n"
        "# Safety analysis\n\n"
        f"```json\n{safety_json}\n```\n\n"
        "# Retrieved context\n\n"
        "<retrieved_context>\n"
        f"{retrieved}\n"
        "</retrieved_context>\n\n"
        "Produce the ReplyOutput JSON now."
    )

    return adapter.parse(
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": user},
        ],
        response_format=ReplyOutput,
        temperature=0.2,
    )
