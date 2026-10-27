"""Ticket domain logic shared by the routers, the AI job runner and the lifecycle sweep."""

from __future__ import annotations

from collections.abc import Iterable

from sqlmodel import Session, col, select

from ..db import utcnow
from ..kb import get_catalog
from ..models import (
    ActionRequest,
    AiRun,
    Attachment,
    AuthorKind,
    Message,
    Priority,
    Ticket,
    TicketEvent,
    TicketStatus,
    User,
    Visibility,
)
from ..schemas import (
    ActionOut,
    AttachmentOut,
    CitationOut,
    EventOut,
    MessageOut,
    RunOut,
    RunProgressOut,
    StageOut,
)
from .pipeline import PipelineResult
from .routing import Decision

AI_NAME = "Everdawn Support Assistant"
SYSTEM_NAME = "Everdawn Support"
PRIORITY_RANK = {p.value: i for i, p in enumerate(Priority)}
TICKET_REF_OFFSET = 1000


def make_ref(ticket_id: int) -> str:
    return f"EVD-{TICKET_REF_OFFSET + ticket_id}"


def subject_from(description: str) -> str:
    first = " ".join(description.strip().split())
    for stop in (". ", "? ", "! "):
        if stop in first[:120]:
            first = first.split(stop, 1)[0] + stop.strip()
            break
    return first[:90] + ("…" if len(first) > 90 else "") or "Screenshot-only request"


# --- Events and status ----------------------------------------------------------


def log_event(
    session: Session,
    ticket: Ticket,
    kind: str,
    *,
    actor_kind: str = "system",
    actor_id: int | None = None,
    **data,
) -> None:
    session.add(TicketEvent(ticket_id=ticket.id, kind=kind, actor_kind=actor_kind, actor_id=actor_id, data=data))


def set_status(
    session: Session,
    ticket: Ticket,
    new: TicketStatus | str,
    *,
    actor_kind: str = "system",
    actor_id: int | None = None,
    reason: str = "",
) -> None:
    new = TicketStatus(new)
    old = ticket.status
    if old == new:
        return
    now = utcnow()
    ticket.status = new
    ticket.updated_at = now
    if new == TicketStatus.pending:
        ticket.pending_since = now
        ticket.reminder_sent_at = None
    elif old == TicketStatus.pending:
        ticket.pending_since = None
    if new == TicketStatus.solved:
        ticket.solved_at = now
        ticket.needs_human = False
        ticket.needs_review = False
    elif old == TicketStatus.solved:
        ticket.solved_at = None
        ticket.resolved_by = None
    if new == TicketStatus.closed:
        ticket.closed_at = now
    log_event(
        session, ticket, "status.changed", actor_kind=actor_kind, actor_id=actor_id,
        **{"from": old.value, "to": new.value, "reason": reason},
    )


def raise_priority(ticket: Ticket, priority: str) -> None:
    if PRIORITY_RANK.get(priority, 0) > PRIORITY_RANK.get(ticket.priority.value, 0):
        ticket.priority = Priority(priority)


def resolved_by_for(session: Session, ticket: Ticket) -> str:
    """'agent' if any staff member replied publicly, otherwise 'ai'."""
    human_reply = session.exec(
        select(Message.id).where(
            Message.ticket_id == ticket.id,
            Message.author_kind == AuthorKind.agent,
            Message.visibility == Visibility.public,
        )
    ).first()
    return "agent" if human_reply else "ai"


def add_message(
    session: Session,
    ticket: Ticket,
    *,
    author_kind: AuthorKind,
    body: str,
    author_id: int | None = None,
    visibility: Visibility = Visibility.public,
    **extra,
) -> Message:
    msg = Message(
        ticket_id=ticket.id, author_kind=author_kind, author_id=author_id, body=body,
        visibility=visibility, **extra,
    )
    session.add(msg)
    ticket.updated_at = utcnow()
    return msg


# --- Conversation for the pipeline ---------------------------------------------------


def compose_conversation(session: Session, ticket: Ticket) -> str:
    """Flatten the public thread into one ticket text for the pipeline.

    Internal notes are excluded on purpose: the player-facing AI must never
    paraphrase internal staff discussion back to the player.
    """
    msgs = session.exec(
        select(Message)
        .where(Message.ticket_id == ticket.id, Message.visibility == Visibility.public)
        .order_by(col(Message.created_at), col(Message.id))
    ).all()
    header = [f"Subject: {ticket.subject}"]
    if ticket.platform:
        header.append(f"Platform (selected by player): {ticket.platform}")
    def with_screens(m: Message) -> str:
        shot = (m.meta or {}).get("screenshot_text")
        return f"{m.body.strip()}\n[Attached screenshots, transcribed]\n{shot}" if shot else m.body.strip()

    if len(msgs) <= 1:
        return "\n".join(header) + "\n\n" + (with_screens(msgs[0]) if msgs else "")
    who = {
        AuthorKind.player: "Player",
        AuthorKind.ai: "Support (AI assistant)",
        AuthorKind.agent: "Support (agent)",
        AuthorKind.system: "Support (automated)",
    }
    lines = [*header, "", "Conversation so far, oldest first. Answer the player's latest message:"]
    for m in msgs:
        lines.append(f"\n--- {who[m.author_kind]} ---\n{with_screens(m)}")
    return "\n".join(lines)


# --- Applying an AI run ------------------------------------------------------------------


def _citations(result: PipelineResult) -> tuple[list[dict], list[dict]]:
    """Player-safe citations (public articles only) plus a few related articles."""
    catalog = get_catalog()
    cited: dict[str, dict] = {}
    for c in result.output.citations:
        art = catalog.resolve_public(article_id=c.article_id, title=c.article)
        if art and art.slug not in cited:
            cited[art.slug] = {"slug": art.slug, "title": art.title, "section": c.section}
    related: dict[str, dict] = {}
    public_hits = [h for h in result.hits if h.audience == "public"]
    # Only suggest related articles that are nearly as relevant as the best match.
    floor = 0.5 * max((h.score for h in public_hits), default=0.0)
    for h in public_hits:
        if h.score < floor:
            continue
        art = catalog.resolve_public(article_id=h.article_id, title=h.title)
        if art and art.slug not in cited and art.slug not in related:
            related[art.slug] = {"slug": art.slug, "title": art.title, "section": ""}
    return list(cited.values()), list(related.values())[:3]


def apply_ai_result(
    session: Session, ticket: Ticket, run: AiRun, result: PipelineResult, decision: Decision
) -> None:
    now = utcnow()
    run.result = result.model_dump(mode="json")
    run.decision = decision.to_dict()

    cls, safety = result.classification, result.safety
    ticket.topic = ticket.topic or cls.primary_topic
    if not ticket.platform and cls.platforms:
        ticket.platform = ", ".join(cls.platforms)
    if safety:
        ticket.language = safety.detected_language or ticket.language
        ticket.pii_flag = ticket.pii_flag or safety.must_redact
        if safety.threat_type != "none":
            ticket.threat_type = safety.threat_type
        ticket.escalated = ticket.escalated or safety.escalation_flag
    ticket.ai_state = "idle"

    if decision.kind == "draft":
        log_event(session, ticket, "ai.draft_ready", actor_kind="ai", run_id=run.id, mode=result.mode)
        return

    if decision.send_to_player:
        cites, related = _citations(result)
        add_message(
            session, ticket, author_kind=AuthorKind.ai, body=result.output.player_reply.strip(),
            ai_run_id=run.id, citations=cites,
            meta={"related": related, "crisis_resources": decision.crisis_resources, "decision": decision.kind},
        )
        ticket.first_response_at = ticket.first_response_at or now

    if run.trigger == "intake":
        add_message(
            session, ticket, author_kind=AuthorKind.ai, visibility=Visibility.internal,
            body=result.output.internal_note.strip(), ai_run_id=run.id, meta={"kind": "ai_internal_note"},
        )

    # A new answer supersedes checklist items the AI asked for earlier and that
    # are still open; staff-requested items stay.
    for old in session.exec(
        select(ActionRequest).where(
            ActionRequest.ticket_id == ticket.id,
            ActionRequest.done == False,  # noqa: E712
            ActionRequest.requested_by == AuthorKind.ai,
        )
    ).all():
        session.delete(old)
    for item in decision.action_items:
        session.add(ActionRequest(ticket_id=ticket.id, text=item, requested_by=AuthorKind.ai, ai_run_id=run.id))

    if decision.priority:
        raise_priority(ticket, decision.priority)
    if decision.needs_human:
        ticket.needs_human = True
        ticket.handoff_reason = decision.handoff_reason
    ticket.needs_review = decision.needs_review
    if decision.status:
        set_status(session, ticket, decision.status, actor_kind="ai", reason=decision.kind)

    qa = result.qa[-1] if result.qa else None
    log_event(
        session, ticket, "ai.escalated" if decision.kind == "escalated" else "ai.replied",
        actor_kind="ai", run_id=run.id, decision=decision.kind, mode=result.mode,
        qa_score=qa.overall_score if qa else None, action_items=len(decision.action_items),
    )


def apply_ai_failure(session: Session, ticket: Ticket, run: AiRun, error: str) -> None:
    ticket.ai_state = "failed"
    log_event(session, ticket, "ai.failed", actor_kind="ai", run_id=run.id, error=error[:500])
    if run.trigger == "agent_draft":
        return
    ticket.needs_human = True
    ticket.handoff_reason = ticket.handoff_reason or "ai_error"
    add_message(
        session, ticket, author_kind=AuthorKind.system,
        body="We couldn't put together an automatic answer this time. A member of the team "
        "has your ticket and will reply here.",
    )
    set_status(session, ticket, TicketStatus.open, reason="ai_error")


# --- Serialization ----------------------------------------------------------------------


def _names(session: Session, ids: Iterable[int | None]) -> dict[int, User]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {u.id: u for u in session.exec(select(User).where(col(User.id).in_(wanted))).all()}


def display_name(user: User | None) -> str:
    if user is None:
        return ""
    return user.display_name or user.email.split("@", 1)[0]


def _attachment_out(a: Attachment) -> AttachmentOut:
    return AttachmentOut(id=a.id, filename=a.filename, mime=a.mime, size=a.size, url=f"/api/attachments/{a.id}")


def messages_out(session: Session, ticket: Ticket, *, include_internal: bool) -> list[MessageOut]:
    stmt = select(Message).where(Message.ticket_id == ticket.id)
    if not include_internal:
        stmt = stmt.where(Message.visibility == Visibility.public)
    msgs = session.exec(stmt.order_by(col(Message.created_at), col(Message.id))).all()
    users = _names(session, (m.author_id for m in msgs))
    atts: dict[int, list[AttachmentOut]] = {}
    for a in session.exec(select(Attachment).where(Attachment.ticket_id == ticket.id)).all():
        if a.message_id:
            atts.setdefault(a.message_id, []).append(_attachment_out(a))
    out = []
    for m in msgs:
        if m.author_kind == AuthorKind.ai:
            name = AI_NAME
        elif m.author_kind == AuthorKind.system:
            name = SYSTEM_NAME
        else:
            name = display_name(users.get(m.author_id))
        out.append(
            MessageOut(
                id=m.id, author_kind=m.author_kind.value, author_name=name, body=m.body,
                visibility=m.visibility.value, created_at=m.created_at,
                citations=[CitationOut(**c) for c in m.citations],
                related=[CitationOut(**c) for c in (m.meta or {}).get("related", [])],
                crisis_resources=bool((m.meta or {}).get("crisis_resources")),
                attachments=atts.get(m.id, []),
            )
        )
    return out


def actions_out(session: Session, ticket: Ticket) -> list[ActionOut]:
    rows = session.exec(
        select(ActionRequest).where(ActionRequest.ticket_id == ticket.id).order_by(col(ActionRequest.id))
    ).all()
    return [
        ActionOut(
            id=a.id, text=a.text, kind=a.kind, requested_by=a.requested_by.value, done=a.done,
            response=a.response, created_at=a.created_at, completed_at=a.completed_at,
        )
        for a in rows
    ]


def _stages(run: AiRun) -> list[StageOut]:
    return [StageOut(**s) for s in run.stages]


def active_run(session: Session, ticket: Ticket, *, include_drafts: bool = False) -> RunProgressOut | None:
    stmt = select(AiRun).where(
        AiRun.ticket_id == ticket.id, col(AiRun.status).in_(["queued", "running"])
    )
    if not include_drafts:
        stmt = stmt.where(AiRun.trigger != "agent_draft")
    run = session.exec(stmt.order_by(col(AiRun.id).desc())).first()
    if run is None:
        return None
    return RunProgressOut(id=run.id, status=run.status.value, trigger=run.trigger, stages=_stages(run), started_at=run.started_at)


def runs_out(session: Session, ticket: Ticket) -> list[RunOut]:
    runs = session.exec(select(AiRun).where(AiRun.ticket_id == ticket.id).order_by(col(AiRun.id).desc())).all()
    return [
        RunOut(
            id=r.id, trigger=r.trigger, persona=r.persona, mode=r.mode, status=r.status.value,
            guidance=r.guidance, stages=_stages(r), result=r.result, decision=r.decision, error=r.error,
            created_at=r.created_at, finished_at=r.finished_at, duration_s=r.duration_s,
        )
        for r in runs
    ]


def events_out(session: Session, ticket: Ticket) -> list[EventOut]:
    evs = session.exec(
        select(TicketEvent).where(TicketEvent.ticket_id == ticket.id).order_by(col(TicketEvent.at), col(TicketEvent.id))
    ).all()
    users = _names(session, (e.actor_id for e in evs))
    names = {"ai": AI_NAME, "system": SYSTEM_NAME}
    return [
        EventOut(
            id=e.id, kind=e.kind, actor_kind=e.actor_kind,
            actor_name=display_name(users.get(e.actor_id)) if e.actor_id else names.get(e.actor_kind, e.actor_kind),
            data=e.data, at=e.at,
        )
        for e in evs
    ]


def open_action_counts(session: Session, ticket_ids: list[int]) -> dict[int, int]:
    if not ticket_ids:
        return {}
    counts: dict[int, int] = {}
    for tid in session.exec(
        select(ActionRequest.ticket_id).where(
            col(ActionRequest.ticket_id).in_(ticket_ids), ActionRequest.done == False  # noqa: E712
        )
    ).all():
        counts[tid] = counts.get(tid, 0) + 1
    return counts


def last_previews(session: Session, ticket_ids: list[int]) -> dict[int, str]:
    if not ticket_ids:
        return {}
    previews: dict[int, str] = {}
    rows = session.exec(
        select(Message.ticket_id, Message.body)
        .where(col(Message.ticket_id).in_(ticket_ids), Message.visibility == Visibility.public)
        .order_by(col(Message.created_at), col(Message.id))
    ).all()
    for tid, body in rows:
        previews[tid] = " ".join(body.split())[:140]
    return previews
