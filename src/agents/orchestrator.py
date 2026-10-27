"""Orchestrator — runs the full multi-agent pipeline for one ticket.

No OpenAI client is passed in — each agent fetches its own adapter from
src/config.py. This keeps the orchestrator provider-agnostic.

Pipeline
--------
Stage 4 (parallel):  Note + Reply + Steps drafting agents
Stage 5 (QA loop):   QA → targeted retries (MAX_RETRIES times)
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..retrieve import Hit
from ..schemas import (
    AgentOutput,
    ClassifierOutput,
    NoteOutput,
    QAResult,
    ReplyOutput,
    SafetyOutput,
    StepsOutput,
)
from .note import run_note
from .qa import run_qa
from .reply import run_reply
from .steps import run_steps

MAX_RETRIES = 1  # QA→fix cycles before giving up


@dataclass
class StageTimings:
    vision: float = 0.0
    classifier: float = 0.0
    retrieval: float = 0.0
    safety: float = 0.0
    drafting: float = 0.0
    qa: list[float] = field(default_factory=list)


@dataclass
class PipelineRun:
    output: AgentOutput
    classification: ClassifierOutput
    safety: SafetyOutput
    note_output: NoteOutput
    reply_output: ReplyOutput
    steps_output: StepsOutput
    qa_results: list[QAResult]
    hits: list[Hit]
    screenshot_text: str = ""
    guidance: str = ""
    retry_count: int = 0
    timings: StageTimings = field(default_factory=StageTimings)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONF_RANK = {"low": 0, "medium": 1, "high": 2}
_RANK_CONF = {v: k for k, v in _CONF_RANK.items()}


def _min_confidence(*confs: str) -> str:
    return _RANK_CONF[min(_CONF_RANK.get(c, 1) for c in confs)]


def _merge_citations(note_out: NoteOutput, reply_out: ReplyOutput, steps_out: StepsOutput):
    seen: set[tuple[str, str]] = set()
    merged = []
    for cit in (*note_out.note_citations, *reply_out.reply_citations, *steps_out.steps_citations):
        key = (cit.article, cit.section)
        if key not in seen:
            seen.add(key)
            merged.append(cit)
    return merged


def _assemble_notes(*notes: str) -> str:
    return " | ".join(n.strip() for n in notes if n.strip())


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------


def run_pipeline(
    ticket: str,
    classification: ClassifierOutput,
    safety: SafetyOutput,
    hits: list[Hit],
    guidance: str = "",
    screenshot_text: str = "",
    timings: StageTimings | None = None,
    on_stage: Callable[[str], None] | None = None,
    persona: str = "human_agent",
) -> PipelineRun:
    """Run stages 4-5 of the pipeline (parallel drafting + QA loop).

    No client/adapter parameters — agents resolve their own adapters from
    src/config.py, which reads environment variables once at startup.
    """
    if timings is None:
        timings = StageTimings()
    report = on_stage or (lambda _label: None)

    # --- Stage 4: Parallel drafting ----------------------------------------
    report("Drafting note, reply, and steps in parallel...")
    t_draft = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        fut_note  = ex.submit(run_note,  ticket, classification, safety, hits)
        fut_reply = ex.submit(run_reply, ticket, classification, safety, hits, guidance, persona=persona)
        fut_steps = ex.submit(run_steps, ticket, classification, safety, hits)
        note_out  = fut_note.result()
        reply_out = fut_reply.result()
        steps_out = fut_steps.result()
    timings.drafting = time.perf_counter() - t_draft

    # --- Stage 5: QA loop --------------------------------------------------
    qa_results: list[QAResult] = []
    retry_count = 0

    for attempt in range(MAX_RETRIES + 1):
        report("QA validation..." if attempt == 0 else f"QA validation (retry {attempt})...")
        t_qa = time.perf_counter()
        qa = run_qa(
            ticket, classification, safety, note_out, reply_out, steps_out, hits, persona=persona
        )
        timings.qa.append(time.perf_counter() - t_qa)
        qa_results.append(qa)

        if qa.passed or attempt >= MAX_RETRIES:
            break

        retry_count += 1
        report(f"Revising drafts from QA feedback (retry {retry_count})...")
        # Targeted retries — only re-run agents that have revision feedback.
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futs: dict[str, concurrent.futures.Future] = {}
            if qa.note_revision.strip():
                futs["note"] = ex.submit(
                    run_note, ticket, classification, safety, hits, qa.note_revision
                )
            if qa.reply_revision.strip():
                futs["reply"] = ex.submit(
                    run_reply, ticket, classification, safety, hits, guidance, qa.reply_revision,
                    persona=persona,
                )
            if qa.steps_revision.strip():
                futs["steps"] = ex.submit(
                    run_steps, ticket, classification, safety, hits, qa.steps_revision
                )
            if "note"  in futs: note_out  = futs["note"].result()
            if "reply" in futs: reply_out = futs["reply"].result()
            if "steps" in futs: steps_out = futs["steps"].result()

    # --- Assemble final AgentOutput ----------------------------------------
    final_qa = qa_results[-1]
    output = AgentOutput(
        internal_note=note_out.internal_note,
        player_reply=reply_out.player_reply,
        next_steps=steps_out.next_steps,
        missing_info=reply_out.missing_info,
        citations=_merge_citations(note_out, reply_out, steps_out),
        escalation_flag=safety.escalation_flag,
        escalation_reason=safety.escalation_reason,
        confidence=_min_confidence(
            note_out.note_confidence, reply_out.reply_confidence, steps_out.steps_confidence
        ),
        notes_for_agent=_assemble_notes(
            note_out.note_agent_notes,
            reply_out.reply_agent_notes,
            steps_out.steps_agent_notes,
            safety.safety_notes,
            final_qa.qa_agent_notes if not final_qa.passed else "",
        ),
    )

    return PipelineRun(
        output=output,
        classification=classification,
        safety=safety,
        note_output=note_out,
        reply_output=reply_out,
        steps_output=steps_out,
        qa_results=qa_results,
        hits=hits,
        screenshot_text=screenshot_text,
        guidance=guidance,
        retry_count=retry_count,
        timings=timings,
    )
