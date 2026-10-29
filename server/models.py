"""Database tables (SQLModel).

Statuses follow the usual helpdesk lifecycle:
  new      → just submitted, the AI is working on it
  open     → needs the support team (handed off, escalated, or the AI failed)
  pending  → waiting on the player (confirm the answer, or complete a checklist)
  on_hold  → waiting on someone internal or a third party (set by staff)
  solved   → resolved; a player reply reopens it until it auto-closes
  closed   → final; a new message means a new ticket
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from .db import utcnow


class Role(StrEnum):
    player = "player"
    agent = "agent"
    admin = "admin"


class TicketStatus(StrEnum):
    new = "new"
    open = "open"
    pending = "pending"
    on_hold = "on_hold"
    solved = "solved"
    closed = "closed"


class Priority(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class AuthorKind(StrEnum):
    player = "player"
    ai = "ai"
    agent = "agent"
    system = "system"


class Visibility(StrEnum):
    public = "public"
    internal = "internal"


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


def _json_list() -> Any:
    return Field(default_factory=list, sa_column=Column(JSON, nullable=False))


def _json_dict() -> Any:
    return Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    display_name: str = ""
    role: Role = Role.player
    password_hash: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    demo: bool = False


class Ticket(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ref: str = Field(default="", index=True)
    requester_id: int = Field(foreign_key="user.id", index=True)
    subject: str = ""
    status: TicketStatus = Field(default=TicketStatus.new, index=True)
    priority: Priority = Priority.normal
    topic: str = ""
    platform: str = ""
    language: str = "en"
    assignee_id: int | None = Field(default=None, foreign_key="user.id")

    # Routing flags
    needs_human: bool = Field(default=False, index=True)
    handoff_reason: str | None = None  # player_request | safety | ai_error
    needs_review: bool = False  # AI answered with low confidence / failed QA
    escalated: bool = False
    threat_type: str = "none"
    pii_flag: bool = False
    ai_state: str = "idle"  # idle | working | failed

    resolved_by: str | None = None  # ai | agent | auto
    csat: int | None = None
    csat_comment: str = ""

    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
    first_response_at: datetime | None = None
    first_human_response_at: datetime | None = None
    pending_since: datetime | None = None
    reminder_sent_at: datetime | None = None
    solved_at: datetime | None = None
    closed_at: datetime | None = None
    demo: bool = False


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id", index=True)
    author_kind: AuthorKind
    author_id: int | None = Field(default=None, foreign_key="user.id")
    body: str
    visibility: Visibility = Visibility.public
    ai_run_id: int | None = Field(default=None, foreign_key="airun.id")
    # For AI messages: player-safe citations [{slug, title, section}] and related articles.
    citations: list[dict] = _json_list()
    meta: dict = _json_dict()
    created_at: datetime = Field(default_factory=utcnow)


class Attachment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id", index=True)
    message_id: int | None = Field(default=None, foreign_key="message.id")
    filename: str
    mime: str
    size: int
    path: str
    transcribed: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class ActionRequest(SQLModel, table=True):
    """One "waiting on you" checklist item for the player."""

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id", index=True)
    text: str
    kind: str = "provide_info"  # provide_info | upload | try_fix
    requested_by: AuthorKind = AuthorKind.ai
    done: bool = False
    response: str = ""
    ai_run_id: int | None = Field(default=None, foreign_key="airun.id")
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


class AiRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id", index=True)
    trigger: str  # intake | player_reply | agent_draft
    persona: str = "ai_assistant"
    mode: str = "mock"  # live | mock
    guidance: str = ""
    status: RunStatus = RunStatus.queued
    stages: list[dict] = _json_list()  # [{key, label, at}]
    result: dict = _json_dict()  # serialized PipelineResult
    decision: dict = _json_dict()  # serialized routing Decision
    error: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: float | None = None


class TicketEvent(SQLModel, table=True):
    """Audit trail: every status change, hand-off, AI decision, assignment, etc."""

    id: int | None = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id", index=True)
    kind: str
    actor_kind: str = "system"  # player | ai | agent | system
    actor_id: int | None = None
    data: dict = _json_dict()
    at: datetime = Field(default_factory=utcnow, index=True)


class ArticleView(SQLModel, table=True):
    """Help-center article feedback, used for deflection reporting."""

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True)
    query: str = ""
    user_id: int | None = Field(default=None, foreign_key="user.id")
    helpful: bool | None = None
    at: datetime = Field(default_factory=utcnow, index=True)
    demo: bool = False
