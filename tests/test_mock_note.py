"""The mock pipeline's internal note summarizes the issue instead of pasting the ticket."""

import re

import pytest

from server.services.mock_pipeline import run_mock


def _note(ticket: str, images: list[bytes] | None = None) -> str:
    result = run_mock(ticket, images=images or [], guidance="", persona="ai_assistant", on_stage=lambda *_: None, fast=True)
    return result.output.internal_note


def _summary(note: str) -> str:
    return re.search(r"^- Summary: (.+)$", note, re.M).group(1)


@pytest.mark.parametrize(
    "ticket, expected",
    [
        (
            "hey so every time i try to queue with my friend on ps5 i get error 105 and it kicks us both, super annoying",
            "Player can't get into matchmaking (Error 105) on PlayStation.",
        ),
        ("I bought the season pass yesterday and nothing showed up in my inventory", "Player reports a problem with a purchase"),
        ("can you tell me when the next event starts?", "Player has a question outside the known topics."),
        ("when does the next event start on switch?", "Player has a question outside the known topics. Platform: Switch."),
    ],
)
def test_summary_paraphrases_the_ticket(ticket, expected):
    summary = _summary(_note(ticket))
    assert summary.startswith(expected)
    assert ticket[:40] not in summary


def test_summary_mentions_screenshots():
    assert _summary(_note("error 105 on steam", images=[b"png"])).endswith("Screenshot attached.")


def test_escalation_leads_with_the_reason():
    assert _summary(_note("I'm calling my lawyer, you stole my skins")).startswith("Player mentions legal action.")


def test_threats_are_quoted_outside_the_summary():
    note = _note("The game keeps crashing. Honestly I want to hurt myself. Nothing works.")
    assert "hurt myself" not in _summary(note)
    assert '- Flagged text (verbatim): "Honestly I want to hurt myself."' in note


def test_follow_ups_ignore_supports_own_words():
    thread = (
        "Subject: penalty\n\nConversation so far, oldest first. Answer the player's latest message:\n"
        "\n--- Player ---\nI got a cooldown penalty after a disconnect\n"
        "\n--- Support (AI assistant) ---\nTell us which platform you play on (PC, PlayStation, Xbox or Switch).\n"
        "\n--- Player ---\n✓ Tell us which platform you play on (PC, PlayStation, Xbox or Switch).\nXbox, last night"
    )
    assert _summary(_note(thread)) == "Player received a disconnect penalty and is asking about it on Xbox."
