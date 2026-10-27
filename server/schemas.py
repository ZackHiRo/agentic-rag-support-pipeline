"""API request/response models.

Kept separate from the tables so the player API can never leak internal
fields (internal notes, AI drafts, safety analysis) by accident.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer


def _iso_utc(d: datetime | None) -> str | None:
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.isoformat().replace("+00:00", "Z")


# Always send timestamps as UTC with an explicit Z so browsers never read them
# as local time.
UTCDateTime = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]


# --- Auth ------------------------------------------------------------------


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    role: str


class MagicLinkIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(default="", max_length=80)


class MagicLinkOut(BaseModel):
    sent: bool
    dev_link: str | None = None  # only when DEV_MAGIC_LINKS=true (no mail server)


class VerifyIn(BaseModel):
    token: str


class LoginIn(BaseModel):
    email: str
    password: str


# --- Knowledge base ----------------------------------------------------------


class ArticleSummary(BaseModel):
    slug: str
    title: str
    summary: str
    category: str


class ArticleSuggestion(ArticleSummary):
    score: float


class ArticleOut(ArticleSummary):
    body: str


class ArticleFeedbackIn(BaseModel):
    helpful: bool
    query: str = Field(default="", max_length=500)


# --- Tickets (player view) -----------------------------------------------------


class CitationOut(BaseModel):
    slug: str
    title: str
    section: str = ""


class AttachmentOut(BaseModel):
    id: int
    filename: str
    mime: str
    size: int
    url: str


class MessageOut(BaseModel):
    id: int
    author_kind: str
    author_name: str
    body: str
    visibility: str
    created_at: UTCDateTime
    citations: list[CitationOut] = []
    related: list[CitationOut] = []
    crisis_resources: bool = False
    attachments: list[AttachmentOut] = []


class ActionOut(BaseModel):
    id: int
    text: str
    kind: str
    requested_by: str
    done: bool
    response: str
    created_at: UTCDateTime
    completed_at: UTCDateTime | None = None


class StageOut(BaseModel):
    key: str
    label: str
    at: UTCDateTime


class RunProgressOut(BaseModel):
    id: int
    status: str
    trigger: str
    stages: list[StageOut]
    started_at: UTCDateTime | None = None


class TicketSummaryOut(BaseModel):
    id: int
    ref: str
    subject: str
    status: str
    priority: str
    topic: str
    needs_human: bool
    ai_state: str
    created_at: UTCDateTime
    updated_at: UTCDateTime
    open_actions: int = 0
    last_message_preview: str = ""


class TicketOut(TicketSummaryOut):
    platform: str
    handoff_reason: str | None
    resolved_by: str | None
    csat: int | None
    messages: list[MessageOut]
    actions: list[ActionOut]
    active_run: RunProgressOut | None = None


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class ActionCompleteIn(BaseModel):
    response: str = Field(default="", max_length=5_000)


class NeedHumanIn(BaseModel):
    reason: str = Field(default="", max_length=2_000)


class CsatIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2_000)


# --- Console (staff view) ------------------------------------------------------


class ConsoleTicketRow(TicketSummaryOut):
    requester_email: str
    requester_name: str
    assignee_id: int | None
    assignee_name: str | None
    platform: str
    escalated: bool
    needs_review: bool
    threat_type: str
    handoff_reason: str | None
    pending_since: UTCDateTime | None


class ConsoleTicketList(BaseModel):
    tickets: list[ConsoleTicketRow]
    counts: dict[str, int]


class EventOut(BaseModel):
    id: int
    kind: str
    actor_kind: str
    actor_name: str
    data: dict
    at: UTCDateTime


class RunOut(BaseModel):
    id: int
    trigger: str
    persona: str
    mode: str
    status: str
    guidance: str
    stages: list[StageOut]
    result: dict
    decision: dict
    error: str
    created_at: UTCDateTime
    finished_at: UTCDateTime | None
    duration_s: float | None


class ConsoleTicketOut(ConsoleTicketRow):
    language: str
    pii_flag: bool
    resolved_by: str | None
    csat: int | None
    csat_comment: str
    first_response_at: UTCDateTime | None
    first_human_response_at: UTCDateTime | None
    solved_at: UTCDateTime | None
    messages: list[MessageOut]
    actions: list[ActionOut]
    events: list[EventOut]
    runs: list[RunOut]


class TicketPatchIn(BaseModel):
    status: str | None = None
    priority: str | None = None
    assignee_id: int | None = None
    unassign: bool = False
    needs_human: bool | None = None
    topic: str | None = None


class ConsoleReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    visibility: str = "public"  # public | internal
    status: str | None = None  # status to set after a public reply (default: pending)
    action_items: list[str] = []  # checklist items to request from the player


class AiDraftIn(BaseModel):
    guidance: str = Field(default="", max_length=4_000)


class StaffOut(BaseModel):
    id: int
    display_name: str
    email: str
    role: str
