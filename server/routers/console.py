"""Support-console API for staff: queue, ticket workspace, replies, AI drafts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import case, func, or_, true
from sqlmodel import Session, col, select

from ..auth import STAFF_ROLES, current_staff
from ..db import get_session, utcnow
from ..models import ActionRequest, AuthorKind, Priority, Ticket, TicketStatus, User, Visibility
from ..schemas import (
    AiDraftIn,
    ConsoleReplyIn,
    ConsoleTicketList,
    ConsoleTicketOut,
    ConsoleTicketRow,
    StaffOut,
    TicketPatchIn,
)
from ..services.events import CONSOLE, notify_ticket, sse_response
from ..services.jobs import enqueue_run
from ..services.tickets import (
    actions_out,
    add_message,
    display_name,
    events_out,
    last_previews,
    log_event,
    messages_out,
    open_action_counts,
    resolved_by_for,
    runs_out,
    set_status,
)

router = APIRouter(prefix="/api/console", tags=["console"])

ACTIVE = (TicketStatus.new, TicketStatus.open, TicketStatus.pending, TicketStatus.on_hold)
VIEWS = ("attention", "review", "mine", "new", "pending", "on_hold", "solved", "closed", "all")


def _view_filter(view: str, me: User):
    return {
        # Tickets a person needs to act on: handed off, escalated, or the AI failed.
        "attention": Ticket.status == TicketStatus.open,
        # AI answered on its own but with low confidence or a failed QA check.
        "review": (Ticket.needs_review == True) & col(Ticket.status).in_(ACTIVE),  # noqa: E712
        "mine": (Ticket.assignee_id == me.id) & col(Ticket.status).in_(ACTIVE),
        "new": Ticket.status == TicketStatus.new,
        "pending": Ticket.status == TicketStatus.pending,
        "on_hold": Ticket.status == TicketStatus.on_hold,
        "solved": Ticket.status == TicketStatus.solved,
        "closed": Ticket.status == TicketStatus.closed,
        "all": true(),
    }[view]


def _row(t: Ticket, users: dict[int, User], counts: dict[int, int], previews: dict[int, str]) -> ConsoleTicketRow:
    requester, assignee = users.get(t.requester_id), users.get(t.assignee_id) if t.assignee_id else None
    return ConsoleTicketRow(
        id=t.id, ref=t.ref, subject=t.subject, status=t.status.value, priority=t.priority.value,
        topic=t.topic, needs_human=t.needs_human, ai_state=t.ai_state, created_at=t.created_at,
        updated_at=t.updated_at, open_actions=counts.get(t.id, 0), last_message_preview=previews.get(t.id, ""),
        requester_email=requester.email if requester else "", requester_name=display_name(requester),
        assignee_id=t.assignee_id, assignee_name=display_name(assignee) if assignee else None,
        platform=t.platform, escalated=t.escalated, needs_review=t.needs_review, threat_type=t.threat_type,
        handoff_reason=t.handoff_reason, pending_since=t.pending_since,
    )


def _users(session: Session, tickets: list[Ticket]) -> dict[int, User]:
    ids = {t.requester_id for t in tickets} | {t.assignee_id for t in tickets if t.assignee_id}
    if not ids:
        return {}
    return {u.id: u for u in session.exec(select(User).where(col(User.id).in_(ids))).all()}


def _get(session: Session, ticket_id: int) -> Ticket:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found.")
    return ticket


def _detail(session: Session, t: Ticket) -> ConsoleTicketOut:
    users = _users(session, [t])
    row = _row(t, users, open_action_counts(session, [t.id]), last_previews(session, [t.id]))
    return ConsoleTicketOut(
        **row.model_dump(),
        language=t.language, pii_flag=t.pii_flag, resolved_by=t.resolved_by, csat=t.csat,
        csat_comment=t.csat_comment, first_response_at=t.first_response_at,
        first_human_response_at=t.first_human_response_at, solved_at=t.solved_at,
        messages=messages_out(session, t, include_internal=True), actions=actions_out(session, t),
        events=events_out(session, t), runs=runs_out(session, t),
    )


@router.get("/tickets", response_model=ConsoleTicketList)
def list_tickets(
    view: str = "attention",
    q: str = "",
    priority: str = "",
    topic: str = "",
    limit: int = 200,
    session: Session = Depends(get_session),
    me: User = Depends(current_staff),
):
    if view not in VIEWS:
        raise HTTPException(422, f"view must be one of {', '.join(VIEWS)}")
    stmt = select(Ticket).where(_view_filter(view, me))
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if topic:
        stmt = stmt.where(Ticket.topic == topic)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.join(User, User.id == Ticket.requester_id).where(
            or_(col(Ticket.ref).ilike(like), col(Ticket.subject).ilike(like), col(User.email).ilike(like))
        )
    prio_rank = case({p.value: i for i, p in enumerate(reversed(list(Priority)))}, value=Ticket.priority)
    if view in ("solved", "closed", "all"):
        stmt = stmt.order_by(col(Ticket.updated_at).desc())
    else:
        # Most urgent first, then oldest first (longest-waiting player).
        stmt = stmt.order_by(prio_rank, col(Ticket.created_at))
    tickets = session.exec(stmt.limit(min(limit, 500))).all()
    ids = [t.id for t in tickets]
    users, counts, previews = _users(session, tickets), open_action_counts(session, ids), last_previews(session, ids)

    view_counts = {
        v: session.exec(select(func.count()).select_from(Ticket).where(_view_filter(v, me))).one()
        for v in VIEWS
    }
    return ConsoleTicketList(tickets=[_row(t, users, counts, previews) for t in tickets], counts=view_counts)


@router.get("/tickets/{ticket_id}", response_model=ConsoleTicketOut)
def get_ticket(ticket_id: int, session: Session = Depends(get_session), _: User = Depends(current_staff)):
    return _detail(session, _get(session, ticket_id))


@router.patch("/tickets/{ticket_id}", response_model=ConsoleTicketOut)
def patch_ticket(
    ticket_id: int, body: TicketPatchIn, session: Session = Depends(get_session), me: User = Depends(current_staff)
):
    t = _get(session, ticket_id)
    actor = {"actor_kind": "agent", "actor_id": me.id}
    if body.priority and body.priority != t.priority.value:
        if body.priority not in Priority.__members__:
            raise HTTPException(422, "Unknown priority.")
        log_event(session, t, "priority.changed", **actor, **{"from": t.priority.value, "to": body.priority})
        t.priority = Priority(body.priority)
    if body.unassign and t.assignee_id:
        log_event(session, t, "assignee.changed", **actor, to=None)
        t.assignee_id = None
    elif body.assignee_id is not None and body.assignee_id != t.assignee_id:
        assignee = session.get(User, body.assignee_id)
        if assignee is None or assignee.role not in STAFF_ROLES:
            raise HTTPException(422, "Assignee must be a staff member.")
        log_event(session, t, "assignee.changed", **actor, to=display_name(assignee))
        t.assignee_id = assignee.id
    if body.needs_human is not None and body.needs_human != t.needs_human:
        t.needs_human = body.needs_human
        if not body.needs_human:
            t.handoff_reason = None
        log_event(session, t, "handoff.changed", **actor, needs_human=body.needs_human)
    if body.topic is not None and body.topic != t.topic:
        log_event(session, t, "topic.changed", **actor, **{"from": t.topic, "to": body.topic})
        t.topic = body.topic
    if body.status and body.status != t.status.value:
        if body.status not in TicketStatus.__members__:
            raise HTTPException(422, "Unknown status.")
        if body.status == TicketStatus.solved:
            t.resolved_by = resolved_by_for(session, t)
        set_status(session, t, body.status, **actor)
    t.updated_at = utcnow()
    session.commit()
    notify_ticket(t.id, "ticket.updated")
    return _detail(session, t)


@router.post("/tickets/{ticket_id}/reply", response_model=ConsoleTicketOut)
def reply(ticket_id: int, body: ConsoleReplyIn, session: Session = Depends(get_session), me: User = Depends(current_staff)):
    t = _get(session, ticket_id)
    if body.visibility not in ("public", "internal"):
        raise HTTPException(422, "visibility must be public or internal.")
    if body.visibility == "internal":
        add_message(session, t, author_kind=AuthorKind.agent, author_id=me.id, body=body.body.strip(), visibility=Visibility.internal)
        log_event(session, t, "note.added", actor_kind="agent", actor_id=me.id)
    else:
        if t.status == TicketStatus.closed:
            raise HTTPException(status.HTTP_409_CONFLICT, "This ticket is closed.")
        now = utcnow()
        add_message(session, t, author_kind=AuthorKind.agent, author_id=me.id, body=body.body.strip())
        t.first_response_at = t.first_response_at or now
        t.first_human_response_at = t.first_human_response_at or now
        # Replying takes ownership: the AI stays out of this ticket from now on.
        t.needs_human = True
        t.handoff_reason = t.handoff_reason or "agent_took_over"
        t.needs_review = False
        t.assignee_id = t.assignee_id or me.id
        for item in (i.strip() for i in body.action_items if i.strip()):
            session.add(ActionRequest(ticket_id=t.id, text=item, requested_by=AuthorKind.agent))
        log_event(session, t, "agent.replied", actor_kind="agent", actor_id=me.id, action_items=len(body.action_items))
        new_status = body.status or TicketStatus.pending.value
        if new_status not in TicketStatus.__members__:
            raise HTTPException(422, "Unknown status.")
        if new_status == TicketStatus.solved:
            t.resolved_by = "agent"
        set_status(session, t, new_status, actor_kind="agent", actor_id=me.id, reason="agent_reply")
    session.commit()
    notify_ticket(t.id, "ticket.updated")
    return _detail(session, t)


@router.post("/tickets/{ticket_id}/ai-draft", response_model=ConsoleTicketOut, status_code=202)
def ai_draft(ticket_id: int, body: AiDraftIn, session: Session = Depends(get_session), me: User = Depends(current_staff)):
    """Ask the copilot for a fresh reply draft (never sent to the player automatically)."""
    t = _get(session, ticket_id)
    log_event(session, t, "ai.draft_requested", actor_kind="agent", actor_id=me.id, guidance=body.guidance[:200])
    # The draft goes out under this agent's name, not the prompt's default persona.
    signer = display_name(me).split()[0]
    guidance = f"Sign the reply as {signer}.\n{body.guidance}".strip()
    enqueue_run(session, t, trigger="agent_draft", guidance=guidance)
    return _detail(session, t)


@router.get("/staff", response_model=list[StaffOut])
def staff(session: Session = Depends(get_session), _: User = Depends(current_staff)):
    users = session.exec(select(User).where(col(User.role).in_([r.value for r in STAFF_ROLES]))).all()
    return [StaffOut(id=u.id, display_name=display_name(u), email=u.email, role=u.role.value) for u in users]


@router.get("/stream")
def stream(request: Request, _: User = Depends(current_staff)):
    return sse_response(request, CONSOLE)
