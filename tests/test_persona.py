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


def test_ai_persona_prompts_contain_no_human_name():
    from src.agents.qa import _system_prompt as qa_prompt
    from src.agents.reply import _system_prompt as reply_prompt

    for prompt in (reply_prompt("ai_assistant"), qa_prompt("ai_assistant")):
        assert "Alex" not in prompt
    assert "I'm the Everdawn Support Assistant, an AI helper" in reply_prompt("ai_assistant")
    assert "This is Alex from the Everdawn team" in reply_prompt("human_agent")  # drafts unchanged


@pytest.mark.parametrize(
    "reply",
    [
        # What the live model actually produced in testing:
        "Hello,\n\nThis is Alex from the Everdawn team,\n\nTry the workaround.\n\nBest regards,\nAlex",
        "Hi Sam,\n\nTry the workaround.\n\nBest regards,\nJordan",
        "Bonjour,\n\nIci Alex, de l'équipe Everdawn,\n\nEssayez ceci.\n\nCordialement,\nAlex",
    ],
)
def test_ai_disclosure_is_enforced(reply):
    from server.services.tickets import ensure_ai_disclosure

    out = ensure_ai_disclosure(reply)
    assert "Alex" not in out and "Jordan" not in out
    assert "Everdawn Support Assistant" in out or "Assistant Support d'Everdawn" in out


def test_ai_disclosure_leaves_compliant_replies_alone():
    from server.services.tickets import ensure_ai_disclosure

    ok = "Hi,\n\nI'm the Everdawn Support Assistant, an AI helper for the Everdawn team.\n\nSteps.\n\nBest regards,\nEverdawn Support Assistant"
    assert ensure_ai_disclosure(ok) == ok
