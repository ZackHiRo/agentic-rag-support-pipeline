"""Player-facing API: help-center articles and the player's own tickets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlmodel import Session, col, select

from ..auth import STAFF_ROLES, current_user, optional_user
from ..db import get_session, utcnow
from ..kb import get_catalog
from ..models import (
    ActionRequest,
    ArticleView,
    Attachment,
    AuthorKind,
    Ticket,
    TicketStatus,
    User,
)
from ..schemas import (
    ArticleFeedbackIn,
    ArticleOut,
    ArticleSuggestion,
    ArticleSummary,
    CsatIn,
    MessageIn,
    NeedHumanIn,
    TicketOut,
    TicketSummaryOut,
)
from ..services.events import notify_ticket, sse_response, ticket_channel
from ..services.jobs import enqueue_run
from ..services.tickets import (
    actions_out,
    active_run,
    add_message,
    last_previews,
    log_event,
    make_ref,
    messages_out,
    open_action_counts,
    resolved_by_for,
    set_status,
    subject_from,
)
from ..uploads import save_uploads

router = APIRouter(prefix="/api", tags=["help"])

HANDOFF_MESSAGE = (
    "Thanks for letting us know. A member of the Everdawn team will take it from here "
    "and reply in this ticket."
)


# --- Knowledge base -------------------------------------------------------------------


@router.get("/kb/articles", response_model=list[ArticleSummary])
def list_articles():
    return [ArticleSummary(slug=a.slug, title=a.title, summary=a.summary, category=a.category) for a in get_catalog().public]


@router.get("/kb/suggest", response_model=list[ArticleSuggestion])
def suggest(q: str = "", limit: int = 5):
    q = q.strip()[:300]
    if len(q) < 3:
        return []
    return [
        ArticleSuggestion(slug=a.slug, title=a.title, summary=a.summary, category=a.category, score=round(s, 3))
        for a, s in get_catalog().suggest(q, limit=min(limit, 8))
    ]


@router.get("/kb/articles/{slug}", response_model=ArticleOut)
def get_article(slug: str):
    art = get_catalog().public_article(slug)
    if art is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found.")
    return ArticleOut(slug=art.slug, title=art.title, summary=art.summary, category=art.category, body=art.body)


@router.post("/kb/articles/{slug}/feedback", status_code=204)
def article_feedback(
    slug: str,
    body: ArticleFeedbackIn,
    session: Session = Depends(get_session),
    user: User | None = Depends(optional_user),
):
    if get_catalog().public_article(slug) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found.")
    session.add(ArticleView(slug=slug, query=body.query, helpful=body.helpful, user_id=user.id if user else None))
    session.commit()


# --- Tickets ---------------------------------------------------------------------------


def _own_ticket(session: Session, ref: str, user: User) -> Ticket:
    ticket = session.exec(select(Ticket).where(Ticket.ref == ref.upper())).first()
    if ticket is None or ticket.requester_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found.")
    return ticket


def _ticket_out(session: Session, ticket: Ticket) -> TicketOut:
    actions = actions_out(session, ticket)
    messages = messages_out(session, ticket, include_internal=False)
    return TicketOut(
        id=ticket.id, ref=ticket.ref, subject=ticket.subject, status=ticket.status.value,
        priority=ticket.priority.value, topic=ticket.topic, needs_human=ticket.needs_human,
        ai_state=ticket.ai_state, created_at=ticket.created_at, updated_at=ticket.updated_at,
        open_actions=sum(1 for a in actions if not a.done),
        last_message_preview=messages[-1].body[:140] if messages else "",
        platform=ticket.platform, handoff_reason=ticket.handoff_reason, resolved_by=ticket.resolved_by,
        csat=ticket.csat, messages=messages, actions=actions, active_run=active_run(session, ticket),
    )


def _continue_conversation(session: Session, ticket: Ticket, *, reason: str) -> None:
    """After the player adds information: the AI answers again, unless a human owns the ticket."""
    if ticket.needs_human:
        set_status(session, ticket, TicketStatus.open, actor_kind="player", reason=reason)
        session.commit()
        notify_ticket(ticket.id, "ticket.updated")
    else:
        set_status(session, ticket, TicketStatus.new, actor_kind="player", reason=reason)
        enqueue_run(session, ticket, trigger="player_reply")


@router.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(
    description: str = Form(default="", max_length=10_000),
    subject: str = Form(default="", max_length=200),
    platform: str = Form(default="", max_length=40),
    files: list[UploadFile] | None = File(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    description = description.strip()
    if not description and not files:
        raise HTTPException(422, "Describe the problem or attach a screenshot.")
    ticket = Ticket(
        requester_id=user.id,
        subject=subject.strip() or subject_from(description),
        platform=platform.strip(),
        status=TicketStatus.new,
    )
    session.add(ticket)
    session.flush()
    ticket.ref = make_ref(ticket.id)
    msg = add_message(session, ticket, author_kind=AuthorKind.player, author_id=user.id, body=description or "(screenshots attached)")
    session.flush()
    save_uploads(session, ticket, msg, files)
    log_event(session, ticket, "ticket.created", actor_kind="player", actor_id=user.id)
    enqueue_run(session, ticket, trigger="intake")
    notify_ticket(ticket.id, "ticket.created")
    session.refresh(ticket)
    return _ticket_out(session, ticket)


@router.get("/tickets", response_model=list[TicketSummaryOut])
def my_tickets(session: Session = Depends(get_session), user: User = Depends(current_user)):
    tickets = session.exec(
        select(Ticket).where(Ticket.requester_id == user.id).order_by(col(Ticket.updated_at).desc())
    ).all()
    ids = [t.id for t in tickets]
    counts, previews = open_action_counts(session, ids), last_previews(session, ids)
    return [
        TicketSummaryOut(
            id=t.id, ref=t.ref, subject=t.subject, status=t.status.value, priority=t.priority.value,
            topic=t.topic, needs_human=t.needs_human, ai_state=t.ai_state, created_at=t.created_at,
            updated_at=t.updated_at, open_actions=counts.get(t.id, 0), last_message_preview=previews.get(t.id, ""),
        )
        for t in tickets
    ]


@router.get("/tickets/{ref}", response_model=TicketOut)
def get_ticket(ref: str, session: Session = Depends(get_session), user: User = Depends(current_user)):
    return _ticket_out(session, _own_ticket(session, ref, user))


@router.get("/tickets/{ref}/stream")
def ticket_stream(ref: str, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)):
    ticket = _own_ticket(session, ref, user)
    return sse_response(request, ticket_channel(ticket.id))


@router.post("/tickets/{ref}/messages", response_model=TicketOut)
def reply(
    ref: str,
    body: str = Form(default="", max_length=10_000),
    files: list[UploadFile] | None = File(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    ticket = _own_ticket(session, ref, user)
    if ticket.status == TicketStatus.closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This ticket is closed. Please open a new one.")
    if ticket.ai_state == "working":
        raise HTTPException(status.HTTP_409_CONFLICT, "Hang on, we're still working on your last message.")
    MessageIn(body=body or "(attachment)")  # validate length
    msg = add_message(session, ticket, author_kind=AuthorKind.player, author_id=user.id, body=body.strip() or "(attachment)")
    session.flush()
    save_uploads(session, ticket, msg, files)
    log_event(session, ticket, "player.replied", actor_kind="player", actor_id=user.id)
    _continue_conversation(session, ticket, reason="player_reply")
    session.refresh(ticket)
    return _ticket_out(session, ticket)


@router.post("/tickets/{ref}/actions/{action_id}/complete", response_model=TicketOut)
def complete_action(
    ref: str,
    action_id: int,
    response: str = Form(default="", max_length=5_000),
    files: list[UploadFile] | None = File(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    ticket = _own_ticket(session, ref, user)
    action = session.get(ActionRequest, action_id)
    if action is None or action.ticket_id != ticket.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist item not found.")
    if action.done:
        return _ticket_out(session, ticket)
    if ticket.status == TicketStatus.closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This ticket is closed. Please open a new one.")
    if not response.strip() and not files:
        raise HTTPException(422, "Add an answer or a file.")
    action.done, action.response, action.completed_at = True, response.strip(), utcnow()
    msg = add_message(
        session, ticket, author_kind=AuthorKind.player, author_id=user.id,
        body=f"✓ {action.text}\n{response.strip() or '(file attached)'}", meta={"action_id": action.id},
    )
    session.flush()
    save_uploads(session, ticket, msg, files)
    log_event(session, ticket, "action.completed", actor_kind="player", actor_id=user.id, action_id=action.id)
    remaining = session.exec(
        select(ActionRequest.id).where(ActionRequest.ticket_id == ticket.id, ActionRequest.done == False)  # noqa: E712
    ).first()
    if remaining is None:
        _continue_conversation(session, ticket, reason="checklist_completed")
    else:
        session.commit()
        notify_ticket(ticket.id, "ticket.updated")
    session.refresh(ticket)
    return _ticket_out(session, ticket)


@router.post("/tickets/{ref}/resolve", response_model=TicketOut)
def resolve(ref: str, session: Session = Depends(get_session), user: User = Depends(current_user)):
    ticket = _own_ticket(session, ref, user)
    if ticket.status not in (TicketStatus.solved, TicketStatus.closed):
        ticket.resolved_by = resolved_by_for(session, ticket)
        set_status(session, ticket, TicketStatus.solved, actor_kind="player", actor_id=user.id, reason="player_confirmed")
        session.commit()
        notify_ticket(ticket.id, "ticket.updated")
    return _ticket_out(session, ticket)


@router.post("/tickets/{ref}/need-human", response_model=TicketOut)
def need_human(ref: str, body: NeedHumanIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    ticket = _own_ticket(session, ref, user)
    if ticket.status == TicketStatus.closed:
        raise HTTPException(status.HTTP_409_CONFLICT, "This ticket is closed. Please open a new one.")
    if not ticket.needs_human:
        if body.reason.strip():
            add_message(session, ticket, author_kind=AuthorKind.player, author_id=user.id, body=body.reason.strip())
        ticket.needs_human = True
        ticket.handoff_reason = "player_request"
        add_message(session, ticket, author_kind=AuthorKind.system, body=HANDOFF_MESSAGE)
        log_event(session, ticket, "handoff.requested", actor_kind="player", actor_id=user.id)
        set_status(session, ticket, TicketStatus.open, actor_kind="player", actor_id=user.id, reason="player_request")
        session.commit()
        notify_ticket(ticket.id, "ticket.updated")
    return _ticket_out(session, ticket)


@router.post("/tickets/{ref}/csat", response_model=TicketOut)
def csat(ref: str, body: CsatIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    ticket = _own_ticket(session, ref, user)
    if ticket.status not in (TicketStatus.solved, TicketStatus.closed):
        raise HTTPException(status.HTTP_409_CONFLICT, "You can rate a ticket once it's solved.")
    ticket.csat, ticket.csat_comment = body.rating, body.comment.strip()
    log_event(session, ticket, "csat.submitted", actor_kind="player", actor_id=user.id, rating=body.rating)
    session.commit()
    notify_ticket(ticket.id, "ticket.updated")
    return _ticket_out(session, ticket)


@router.get("/attachments/{attachment_id}")
def attachment(attachment_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    att = session.get(Attachment, attachment_id)
    ticket = session.get(Ticket, att.ticket_id) if att else None
    if att is None or ticket is None or (ticket.requester_id != user.id and user.role not in STAFF_ROLES):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    return FileResponse(att.path, media_type=att.mime, filename=att.filename)
