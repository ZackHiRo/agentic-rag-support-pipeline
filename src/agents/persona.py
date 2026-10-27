"""Persona handling for player replies.

The base prompts are written for a human agent ("This is Alex from the
Everdawn team,"). When the AI answers players directly it must say it is an AI,
and an appended "override" is not enough: models follow the majority of the
prompt. So for the AI persona the human-agent phrases are rewritten in place,
leaving no human name in the prompt at all.
"""

from __future__ import annotations

import re

AI_NAME = "Everdawn Support Assistant"
AI_INTRO_EN = "I'm the Everdawn Support Assistant, an AI helper for the Everdawn team."
AI_INTRO_FR = "Je suis l'Assistant Support d'Everdawn, une IA qui aide l'équipe Everdawn."

_REWRITES = (
    ("This is Alex from the Everdawn team,", AI_INTRO_EN),
    ("Ici Alex, de l'équipe Everdawn,", AI_INTRO_FR),
    ('Use "Alex" unless the ticket or retrieved context explicitly names a different agent.',
     "You are the AI assistant: never use a human agent's name or claim to be human."),
    ('"Alex & The Everdawn Support Team"', '"Everdawn Support Assistant & The Everdawn Support Team"'),
)


def to_ai_persona(prompt: str) -> str:
    """Rewrite a human-agent prompt so it describes the AI assistant persona."""
    for old, new in _REWRITES:
        prompt = prompt.replace(old, new)
    # Remaining mentions are sign-offs ("Best regards,\nAlex", `Alex`).
    return re.sub(r"\bAlex\b", AI_NAME, prompt)
