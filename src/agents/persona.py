"""Persona handling for player replies.

The base prompts are written for a human agent ("This is Alex from the
Everdawn team,"). When the AI answers players directly it keeps a friendly
name but must say plainly that it is an AI. An appended "override" is not
enough (models follow the majority of the prompt), so for the AI persona the
human-agent phrases are rewritten in place.

The assistant's name is configurable with AI_ASSISTANT_NAME (default "Alex").
"""

from __future__ import annotations

import os
import re

AI_NAME = os.getenv("AI_ASSISTANT_NAME", "Alex").strip() or "Alex"
AI_TITLE = "AI Support Assistant"
AI_INTRO_EN = f"I'm {AI_NAME}, the Everdawn team's AI support assistant."
AI_INTRO_FR = f"Ici {AI_NAME}, l'assistant IA de l'équipe Everdawn."
AI_SIGNATURE = f"{AI_NAME}, {AI_TITLE}"

# Phrases that count as disclosing the reply comes from an AI.
DISCLOSURE_RE = re.compile(r"\bAI support assistant\b|\bassistant IA\b", re.I)

_REWRITES = (
    ("This is Alex from the Everdawn team,", AI_INTRO_EN),
    ("Ici Alex, de l'équipe Everdawn,", AI_INTRO_FR),
    (
        'Use "Alex" unless the ticket or retrieved context explicitly names a different agent.',
        f"Always introduce yourself as {AI_NAME}, the AI support assistant. Never claim to be human.",
    ),
    ('"Alex & The Everdawn Support Team"', f'"{AI_NAME} & The Everdawn Support Team"'),
    ("'Best regards, Alex'", f"'Best regards, {AI_SIGNATURE}'"),
    ("`Alex`", f"`{AI_SIGNATURE}`"),
)
# A sign-off line that is just the name. Anchored to the end of the line so an
# already-correct "Alex, AI Support Assistant" is left alone.
_BARE_SIGNOFF_RE = re.compile(r"^(\s*)Alex\s*$", re.M)


def to_ai_persona(prompt: str) -> str:
    """Rewrite a human-agent prompt so it describes the named AI assistant."""
    for old, new in _REWRITES:
        prompt = prompt.replace(old, new)
    prompt = _BARE_SIGNOFF_RE.sub(lambda m: f"{m.group(1)}{AI_SIGNATURE}", prompt)
    if AI_NAME != "Alex":
        prompt = re.sub(r"\bAlex\b", AI_NAME, prompt)
    return prompt
