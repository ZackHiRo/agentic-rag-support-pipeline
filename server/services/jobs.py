"""AI job runner: executes pipeline runs on worker threads.

The pipeline is synchronous and takes ~5s (mock) to ~60s (live), so runs go to
a small thread pool. Each stage is persisted on the AiRun row (so a page
refresh mid-run still shows progress) and pushed to SSE subscribers.

Single-process by design for the prototype; the scale-out path is a real queue
(e.g. arq/RQ on Redis) with the same enqueue_run() interface.
"""

from __future__ import annotations

import logging
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from sqlmodel import Session, col, select

from ..db import engine, utcnow
from ..models import AiRun, Attachment, Message, RunStatus, Ticket, TicketStatus
from ..settings import settings
from .events import notify_ticket
from .pipeline import run_pipeline
from .routing import RunSignals, decide
from .tickets import apply_ai_failure, apply_ai_result, compose_conversation, log_event

log = logging.getLogger("everdawn.jobs")

_executor = ThreadPoolExecutor(max_workers=settings.ai_workers, thread_name_prefix="ai-run")
_futures: set[Future] = set()


def enqueue_run(session: Session, ticket: Ticket, *, trigger: str, guidance: str = "") -> AiRun:
    """Create a queued AiRun and schedule it. Commits the session."""
    persona = "human_agent" if trigger == "agent_draft" else "ai_assistant"
    run = AiRun(ticket_id=ticket.id, trigger=trigger, persona=persona, mode=settings.pipeline_mode, guidance=guidance)
    session.add(run)
    if trigger != "agent_draft":
        ticket.ai_state = "working"
    session.commit()
    session.refresh(run)
    notify_ticket(ticket.id, "run.queued", run_id=run.id, trigger=trigger)
    fut = _executor.submit(execute_run, run.id)
    _futures.add(fut)
    fut.add_done_callback(_futures.discard)
    return run


def recover_interrupted_runs() -> int:
    """Called at startup: runs a restart or crash left queued/running would
    otherwise keep their tickets on "Working on it" forever. Mark them failed and
    re-queue the player-facing ones (staff can simply ask for a new draft)."""
    with Session(engine) as s:
        stale = s.exec(select(AiRun).where(col(AiRun.status).in_([RunStatus.queued, RunStatus.running]))).all()
        retry: list[tuple[int, str, str]] = []
        for run in stale:
            run.status, run.error, run.finished_at = RunStatus.failed, "Interrupted by a server restart.", utcnow()
            ticket = s.get(Ticket, run.ticket_id)
            log_event(s, ticket, "ai.interrupted", actor_kind="system", run_id=run.id)
            if run.trigger != "agent_draft" and ticket.status not in (TicketStatus.solved, TicketStatus.closed):
                retry.append((ticket.id, run.trigger, run.guidance))
        s.commit()
        for ticket_id, trigger, guidance in retry:
            enqueue_run(s, s.get(Ticket, ticket_id), trigger=trigger, guidance=guidance)
    if stale:
        log.warning("recovered %d interrupted AI run(s); re-queued %d", len(stale), len(retry))
    return len(stale)


def wait_idle(timeout: float = 30.0) -> None:
    """Block until queued runs finish (used by tests and graceful shutdown)."""
    deadline = time.monotonic() + timeout
    while _futures and time.monotonic() < deadline:
        time.sleep(0.02)


def _record_stage(run_id: int, ticket_id: int, key: str, label: str) -> None:
    with Session(engine) as s:
        run = s.get(AiRun, run_id)
        if run is None:
            return
        stage = {"key": key, "label": label, "at": utcnow().isoformat()}
        run.stages = [*run.stages, stage]  # reassign so SQLAlchemy sees the JSON change
        s.add(run)
        s.commit()
    notify_ticket(ticket_id, "run.stage", run_id=run_id, key=key, label=label)


def _load_images(session: Session, ticket_id: int) -> tuple[list[Attachment], list[bytes]]:
    """Images not yet transcribed. Earlier screenshots are already in the thread as text."""
    atts = session.exec(
        select(Attachment).where(
            Attachment.ticket_id == ticket_id,
            Attachment.transcribed == False,  # noqa: E712
            col(Attachment.mime).startswith("image/"),
        )
    ).all()
    images = []
    for a in atts:
        try:
            images.append(Path(a.path).read_bytes())
        except OSError:
            log.warning("attachment %s missing on disk", a.id)
    return list(atts), images


def execute_run(run_id: int) -> None:
    with Session(engine) as s:
        run = s.get(AiRun, run_id)
        ticket = s.get(Ticket, run.ticket_id) if run else None
        if run is None or ticket is None:
            return
        run.status = RunStatus.running
        run.started_at = utcnow()
        s.commit()
        ticket_id, trigger, guidance, persona = ticket.id, run.trigger, run.guidance, run.persona
        text = compose_conversation(s, ticket)
        atts, images = _load_images(s, ticket_id) if trigger != "agent_draft" else ([], [])
    notify_ticket(ticket_id, "run.started", run_id=run_id)

    t0 = time.perf_counter()
    try:
        result = run_pipeline(
            text,
            images=images,
            guidance=guidance,
            persona=persona,  # type: ignore[arg-type]
            on_stage=lambda key, label: _record_stage(run_id, ticket_id, key, label),
        )
        error = None
    except Exception as exc:  # the pipeline talks to external APIs; anything can fail
        log.exception("AI run %s failed", run_id)
        result, error = None, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"

    with Session(engine) as s:
        run = s.get(AiRun, run_id)
        ticket = s.get(Ticket, ticket_id)
        run.finished_at = utcnow()
        run.duration_s = round(time.perf_counter() - t0, 2)
        if result is None:
            run.status = RunStatus.failed
            run.error = error or "unknown error"
            apply_ai_failure(s, ticket, run, run.error)
        else:
            run.status = RunStatus.succeeded
            safety = result.safety
            decision = decide(
                RunSignals(
                    trigger=trigger,
                    escalation_flag=bool(safety and safety.escalation_flag),
                    threat_type=safety.threat_type if safety else "none",
                    threat_is_urgent=bool(safety and safety.threat_is_urgent),
                    missing_info=tuple(result.output.missing_info),
                    qa_passed=result.qa_passed,
                    confidence=result.output.confidence,
                )
            )
            apply_ai_result(s, ticket, run, result, decision)
            done = s.exec(select(Attachment).where(col(Attachment.id).in_([a.id for a in atts]))).all()
            for a in done:
                a.transcribed = True
            # Keep the transcription with the player's message so later runs (which
            # no longer re-send the images) still see what the screenshots said.
            if result.screenshot_text:
                for mid in {a.message_id for a in done if a.message_id}:
                    msg = s.get(Message, mid)
                    msg.meta = {**(msg.meta or {}), "screenshot_text": result.screenshot_text}
        s.commit()
        status = run.status.value
    notify_ticket(ticket_id, "run.finished", run_id=run_id, status=status, trigger=trigger)
