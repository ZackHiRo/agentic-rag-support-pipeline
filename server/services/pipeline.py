"""Bridge between the platform and the multi-agent pipeline in src/.

`run_pipeline()` returns one `PipelineResult` shape whether the run was live
(src.agent.run_agent, real LLM calls) or mock (server.services.mock_pipeline,
no API calls). Everything downstream (routing, storage, UI) only sees this.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from src.schemas import AgentOutput, ClassifierOutput, QAResult, SafetyOutput

from ..settings import settings

Persona = Literal["ai_assistant", "human_agent"]
StageCallback = Callable[[str, str], None]  # (key, label)

# Map pipeline stage labels (src.agent on_stage) to stable keys for the UI.
_STAGE_KEYS = (
    ("Reading", "vision"),
    ("Classifying", "classify"),
    ("Retrieving", "retrieve"),
    ("Drafting", "draft"),
    ("QA validation", "qa"),
    ("Revising", "revise"),
)


def stage_key(label: str) -> str:
    return next((key for prefix, key in _STAGE_KEYS if label.startswith(prefix)), "other")


class HitSummary(BaseModel):
    chunk_id: str
    article_id: str = ""
    title: str = ""
    heading: str = ""
    type: str = ""
    audience: str = "internal"
    score: float = 0.0
    source: str = ""


class PipelineResult(BaseModel):
    mode: Literal["live", "mock"]
    persona: Persona
    output: AgentOutput
    classification: ClassifierOutput
    safety: SafetyOutput | None = None
    qa: list[QAResult] = Field(default_factory=list)
    retry_count: int = 0
    hits: list[HitSummary] = Field(default_factory=list)
    timings: dict = Field(default_factory=dict)
    screenshot_text: str = ""
    note_confidence: str = "medium"
    reply_confidence: str = "medium"
    steps_confidence: str = "medium"

    @property
    def qa_passed(self) -> bool | None:
        return self.qa[-1].passed if self.qa else None


def _run_live(
    ticket: str, images: list[bytes], guidance: str, persona: Persona, on_stage: StageCallback
) -> PipelineResult:
    # Imported lazily: pulls in chromadb/openai, which mock mode never needs.
    from src.agent import run_agent

    run = run_agent(
        ticket,
        images=images or None,
        guidance=guidance,
        on_stage=lambda label: on_stage(stage_key(label), label),
        persona=persona,
    )
    pr = run.pipeline_run
    t = run.timings
    return PipelineResult(
        mode="live",
        persona=persona,
        output=run.output,
        classification=run.classification,
        safety=run.safety,
        qa=run.qa_results,
        retry_count=run.retry_count,
        hits=[
            HitSummary(
                chunk_id=h.chunk_id,
                article_id=str((h.metadata or {}).get("article_id", "")),
                title=h.title,
                heading=h.heading,
                type=str((h.metadata or {}).get("type", "")),
                audience=str((h.metadata or {}).get("audience", "internal")),
                score=h.score,
                source=h.source,
            )
            for h in run.hits
        ],
        timings={
            "vision": t.vision,
            "classifier": t.classifier,
            "retrieval": t.retrieval,
            "safety": t.safety,
            "drafting": t.drafting,
            "qa": list(t.qa),
        },
        screenshot_text=run.screenshot_text,
        note_confidence=pr.note_output.note_confidence if pr else "medium",
        reply_confidence=pr.reply_output.reply_confidence if pr else "medium",
        steps_confidence=pr.steps_output.steps_confidence if pr else "medium",
    )


def run_pipeline(
    ticket: str,
    *,
    images: list[bytes] | None = None,
    guidance: str = "",
    persona: Persona = "ai_assistant",
    on_stage: StageCallback | None = None,
    mode: str | None = None,
) -> PipelineResult:
    report: StageCallback = on_stage or (lambda _k, _l: None)
    mode = (mode or settings.pipeline_mode).lower()
    if mode == "live":
        return _run_live(ticket, images or [], guidance, persona, report)
    from .mock_pipeline import run_mock

    return run_mock(ticket, images=images or [], guidance=guidance, persona=persona, on_stage=report)
