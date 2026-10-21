"""Build the three always-on prompt bundles from handbook articles in kb/.

Reads selected `.md` files from `kb/general/handbook/` and `kb/general/procedures/`
and produces concatenated bundles at:

    prompts/tone_rules.md       -- voice, structure, grammar, stylization
    prompts/note_format.md      -- internal note schema (verbatim)
    prompts/process_rules.md    -- PII, multiple issues, third parties, language, escalation

These bundles are injected into the system prompt at runtime by src/agent.py.
Keeping them as generated files (instead of baking the text into Python) means
you can edit the underlying `.md` source articles and rebuild with one command.

Usage:
    python -m src.build_prompts
"""

from __future__ import annotations

import sys
from pathlib import Path

import frontmatter

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "kb"
OUT = ROOT / "prompts"

# Always-on bundles must stay small enough to fit comfortably under the
# OpenAI org-level TPM ceiling (currently 30K on tier 1). Anything that is
# pure reference / lookup material lives only in the retrieval pool: it is
# still indexed in kb/ and will surface via RAG when the ticket needs it.
#
# Rule of thumb for "always-on":
#   - Voice/tone essentials that must shape every reply.
#   - Safety rules (PII, escalation, threats, controversial).
#   - The internal-note schema (must be reproduced verbatim every time).
#   - The language-handling rule (small, must be enforced every reply).
TONE_SOURCES = [
    "general/handbook/communication-general-guidelines.md",
    "general/handbook/communication-stylization-guide.md",
]

NOTE_FORMAT_SOURCES = [
    "general/handbook/documentation-internal-notes.md",
]

PROCESS_SOURCES = [
    "general/handbook/general-pii-redaction.md",
    "general/handbook/general-supported-and-unsupported-language-tickets.md",
    "general/handbook/general-handling-tickets-submitted-on-behalf-of-a-third-party.md",
    "general/procedures/general-escalations-and-de-escalations.md",
    "general/procedures/general-controversial-cases.md",
    "general/procedures/general-threats-sensitive-inquiries.md",
]

# These articles used to be always-on but are now retrieval-only. Listed here
# purely for documentation; they are still indexed in kb/ and the retriever
# will pull them whenever the ticket actually needs that material.
RETRIEVAL_ONLY_REFERENCE = [
    "general/handbook/communication-writing-emails-tips-inspiration.md",
    "general/handbook/communication-structure-formatting.md",
    "general/handbook/communication-punctuation-grammar.md",
    "general/handbook/communication-purchase-buy-and-own-replacement-options.md",
    "general/handbook/general-handling-tickets.md",
    "general/handbook/general-multiple-issues-in-the-same-ticket.md",
    "general/handbook/general-email-format-issues.md",
    "general/handbook/documentation-ticket-fields-and-forms.md",
]


HEADER_TONE = """# Tone rules (always apply)

The following is the normative agent voice guidance baked from our handbook.
Apply it to every player-facing reply. Do NOT paraphrase or soften these rules
away just because the ticket is short.

"""

HEADER_NOTE = """# Internal note format (always apply)

The `internal_note` output MUST follow the schema defined below, taken verbatim
from our internal documentation handbook. Preserve the three-part structure
(Identification → Assessment → Resolution), section names, and field ordering.

"""

HEADER_PROCESS = """# Process rules (always apply)

Ticket-handling policies that apply regardless of the specific SOP in use:
PII redaction, handling multiple issues in one ticket, third-party tickets,
supported languages, escalation criteria, etc.

"""


def load_body(rel: str) -> tuple[str, str]:
    path = KB / rel
    if not path.exists():
        raise FileNotFoundError(f"Missing KB file required by build_prompts: {rel}")
    post = frontmatter.load(path)
    title = post.metadata.get("title", path.stem)
    return str(title), post.content.strip()


def bundle(sources: list[str], header: str) -> str:
    parts: list[str] = [header.rstrip() + "\n"]
    for rel in sources:
        try:
            title, body = load_body(rel)
        except FileNotFoundError as exc:
            print(f"[warn] {exc}", file=sys.stderr)
            continue
        parts.append(f"\n---\n\n## Source: {title}\n\n_Origin: `{rel}`_\n\n{body}\n")
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    all_sources = TONE_SOURCES + NOTE_FORMAT_SOURCES + PROCESS_SOURCES
    existing = [s for s in all_sources if (KB / s).exists()]
    if not existing:
        print("[info] No raw handbook articles found in kb/ to rebuild prompts. Keeping existing prompt files.")
        return 0

    bundles = {
        "tone_rules.md": bundle(TONE_SOURCES, HEADER_TONE),
        "note_format.md": bundle(NOTE_FORMAT_SOURCES, HEADER_NOTE),
        "process_rules.md": bundle(PROCESS_SOURCES, HEADER_PROCESS),
    }
    for name, content in bundles.items():
        out_path = OUT / name
        out_path.write_text(content, encoding="utf-8")
        print(f"[built] {out_path.relative_to(ROOT)}  ({len(content):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
