"""The live pipeline's persona wiring, checked with fake LLM adapters (no API calls)."""

import pytest

from src.agents import note, orchestrator, qa, reply, steps
from src.schemas import ClassifierOutput, NoteOutput, QAResult, ReplyOutput, SafetyOutput, StepsOutput

CANNED = {
    NoteOutput: NoteOutput(internal_note="note"),
    ReplyOutput: ReplyOutput(player_reply="reply"),
    StepsOutput: StepsOutput(next_steps=["step"]),
    QAResult: QAResult(overall_score=1.0, passed=True),
}


class FakeAdapter:
    def __init__(self, log: dict):
        self.log = log

    def parse(self, *, messages, response_format, temperature=0.0):
        self.log[response_format.__name__] = messages
        return CANNED[response_format]


@pytest.fixture
def captured(monkeypatch):
    log: dict = {}
    for mod, fn in ((note, "get_note_adapter"), (reply, "get_reply_adapter"), (steps, "get_steps_adapter"), (qa, "get_qa_adapter")):
        monkeypatch.setattr(mod, fn, lambda log=log: FakeAdapter(log))
    return log


def _run(persona):
    return orchestrator.run_pipeline(
        ticket="Error 105", classification=ClassifierOutput(primary_topic="x"), safety=SafetyOutput(), hits=[], persona=persona
    )


def test_ai_persona_reaches_reply_and_qa(captured):
    _run("ai_assistant")
    reply_system = captured["ReplyOutput"][0]["content"]
    assert "Persona override: Everdawn Support Assistant (AI)" in reply_system
    # Appended after the tone rules, so it overrides their "This is Alex" intro rule.
    assert reply_system.index("Persona override") > reply_system.index("<tone_rules>")
    assert "Reply persona: AI assistant" in captured["QAResult"][1]["content"]


def test_human_persona_is_unchanged(captured):
    _run("human_agent")
    assert "Persona override" not in captured["ReplyOutput"][0]["content"]
    assert "Reply persona: AI assistant" not in captured["QAResult"][1]["content"]
