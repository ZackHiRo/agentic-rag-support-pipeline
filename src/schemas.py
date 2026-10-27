"""Pydantic models shared by the ingestion pipeline, the retriever, and the agent.

Layout
------
- Infrastructure models: FrontMatter, Chunk, Hit-adjacent
- LLM I/O models (per-agent outputs): ClassifierOutput, SafetyOutput,
  NoteOutput, ReplyOutput, StepsOutput
- Quality models: QACheck, QAResult
- Pipeline model: AgentOutput (the final assembled result), AgentRun
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Article / KB metadata
# ---------------------------------------------------------------------------

ArticleType = Literal["procedure", "reference", "known-issue", "patch-note", "handbook", "help-article"]
ArticleCategory = Literal["game", "general"]


class FrontMatter(BaseModel):
    """Metadata at the top of every kb/*.md file."""

    id: str
    title: str
    type: ArticleType
    category: ArticleCategory
    slug: str
    source_url: str = ""
    source_html: str = ""
    source_hash: str = ""
    last_updated: str = ""
    audience: Literal["public", "internal"] = "internal"


class Chunk(BaseModel):
    """A single retrievable unit (one heading section of one article)."""

    chunk_id: str  # f"{article_id}::{heading_path}"
    article_id: str
    title: str
    type: ArticleType
    category: ArticleCategory
    source_url: str
    heading_path: str  # e.g. "Investigation > DC Penalty Appeals"
    text: str
    token_count: int


# ---------------------------------------------------------------------------
# Shared output primitives
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    """One source entry the agent used to support its draft."""

    article: str = Field(description="Human-readable article title.")
    section: str = Field(description="Heading path inside the article, e.g. 'Procedures > DC Penalty Appeals'.")
    article_id: str = Field(default="", description="Knowledge-base article id if known.")
    source_url: str = Field(default="")


# ---------------------------------------------------------------------------
# Stage 1 – Classifier
# ---------------------------------------------------------------------------


class ClassifierOutput(BaseModel):
    """Output of the cheap classifier pass that runs before retrieval."""

    primary_topic: str = Field(description="Short label of the main issue, e.g. 'ban_appeal', 'refund', 'tech_connection'.")
    platforms: list[str] = Field(default_factory=list, description="PC, PS4, PS5, Xbox, Switch, Stadia, Mobile, etc. Empty if not mentioned.")
    suspected_category: Literal["game", "general", "unknown"] = "unknown"
    urgency: Literal["low", "medium", "high"] = "medium"
    is_bug_report: bool = False
    is_ban_related: bool = False
    is_billing_related: bool = False
    is_mclop_related: bool = Field(default=False, description="Missing Content / Loss of Progress.")
    player_language: str = Field(default="en", description="ISO 639-1 best guess.")
    extracted_ids: list[str] = Field(default_factory=list, description="Account IDs, order numbers, error codes, etc.")
    search_queries: list[str] = Field(default_factory=list, description="Two or three search query strings to feed retrieval.")


# ---------------------------------------------------------------------------
# Stage 2 – Safety Agent
# ---------------------------------------------------------------------------


class PIIItem(BaseModel):
    """One piece of detected PII."""

    pii_type: str = Field(description="e.g. 'phone_number', 'password', 'full_address', 'national_id', 'credit_card_full', 'ssn'.")
    location: str = Field(description="Brief description of where in the ticket the PII was found (e.g. 'ticket body, paragraph 2').")
    must_redact: bool = Field(description="True if this requires redaction per the PII policy (passwords, phone, full address, national ID, full credit card, SSN). False for non-redactable items like full name or email.")


class SafetyOutput(BaseModel):
    """Output of the Safety Agent. Downstream agents treat this as ground truth for PII/escalation."""

    # PII
    pii_detected: list[PIIItem] = Field(default_factory=list, description="All PII items found in the ticket. Empty if none.")
    must_redact: bool = Field(default=False, description="True if any pii_detected item has must_redact=True.")

    # Escalation
    escalation_flag: bool = Field(default=False, description="True if this ticket must be escalated per the escalation SOPs.")
    escalation_reason: str = Field(default="", description="Concise explanation of why escalation is required.")
    escalation_target: str = Field(
        default="",
        description="Who to escalate to: 'Support Leadership', 'Tier 3 Support', 'Player Conduct', or 'Tier 3 (silent)'.",
    )

    # Threat classification (subset of escalation)
    threat_type: Literal["none", "legal", "rlt_self_harm", "rlt_violence", "sensitive_inquiry", "controversial"] = "none"
    threat_is_urgent: bool = Field(
        default=False,
        description="True only for RLT threats where all three criteria are met: Intent + Location + Timeframe.",
    )

    # Third-party / special flags
    is_third_party_ticket: bool = Field(default=False, description="True if the reporter is acting on behalf of another player.")
    is_unsupported_language: bool = Field(default=False, description="True if the ticket language is not in the supported-language list.")
    detected_language: str = Field(default="en", description="ISO 639-1 best guess of the ticket language.")

    # Agent notes
    safety_notes: str = Field(
        default="",
        description="Short meta-note for the human agent, e.g. 'PII in body - redact before sending reply'.",
    )


# ---------------------------------------------------------------------------
# Stage 3 – Drafting Agents (individual outputs)
# ---------------------------------------------------------------------------


class NoteOutput(BaseModel):
    """Output of the Internal Note Agent."""

    internal_note: str = Field(
        description="Markdown internal note following the three-part schema: "
        "Identification (Customer ID, Platform; Reported User ID and Reference ID only when it's a player report), "
        "Assessment (concise Summary including error message/code if present, Findings, Matched Documentation), "
        "Resolution (Actions Taken, PII Status, Escalation). "
        "Use '(pending)' for fields the human still needs to fill in."
    )
    note_citations: list[Citation] = Field(default_factory=list, description="SOP sections referenced in the note.")
    note_confidence: Literal["low", "medium", "high"] = "medium"
    note_agent_notes: str = Field(default="", description="Meta-note to the human agent about the internal note.")


class ReplyOutput(BaseModel):
    """Output of the Player Reply Agent."""

    player_reply: str = Field(
        description="Ready-to-paste public reply. Follows the Communication handbook tone rules. "
        "Must open with friendly greeting ('Hello [Name],' or 'Hi,') followed by agent intro line ('This is Alex from the Everdawn team,'). "
        "Closes cleanly with 'Best regards,\\nAlex'. "
        "Must match the ticket's language."
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description="Questions to ask the player if information is missing to proceed.",
    )
    reply_citations: list[Citation] = Field(default_factory=list, description="SOP sections referenced in the reply.")
    reply_confidence: Literal["low", "medium", "high"] = "medium"
    reply_agent_notes: str = Field(default="", description="Meta-note to the human agent about the reply.")


class StepsOutput(BaseModel):
    """Output of the Next Steps Agent."""

    next_steps: list[str] = Field(description="Ordered investigation/action items for the human agent to perform.")
    steps_citations: list[Citation] = Field(default_factory=list, description="SOP sections the steps were drawn from.")
    steps_confidence: Literal["low", "medium", "high"] = "medium"
    steps_agent_notes: str = Field(default="", description="Meta-note to the human agent about the next steps.")


# ---------------------------------------------------------------------------
# Stage 4 – QA Agent
# ---------------------------------------------------------------------------

QASeverity = Literal["critical", "major", "minor"]
QACategory = Literal["hard_rule", "tone", "process", "formatting", "language", "citations"]


class QACheck(BaseModel):
    """One rule evaluated by the QA Agent."""

    rule_id: str = Field(description="Short snake_case identifier, e.g. 'agent_intro_line', 'no_invented_procedures'.")
    category: QACategory
    severity: QASeverity
    passed: bool
    detail: str = Field(default="", description="What was wrong (empty when passed=True).")


class QAResult(BaseModel):
    """Output of the QA Agent pass."""

    overall_score: float = Field(description="0.0–1.0. Weighted: critical=1.0, major=0.5, minor=0.1.")
    passed: bool = Field(description="True if all critical checks pass and overall_score >= 0.80.")
    checks: list[QACheck] = Field(default_factory=list)

    # Targeted retry instructions keyed by agent name
    note_revision: str = Field(default="", description="Feedback for the Internal Note Agent on retry. Empty if no note issues.")
    reply_revision: str = Field(default="", description="Feedback for the Player Reply Agent on retry. Empty if no reply issues.")
    steps_revision: str = Field(default="", description="Feedback for the Next Steps Agent on retry. Empty if no steps issues.")

    qa_agent_notes: str = Field(default="", description="Overall QA commentary for the human agent.")


# ---------------------------------------------------------------------------
# Final assembled output (what the UI receives)
# ---------------------------------------------------------------------------


class AgentOutput(BaseModel):
    """The final structured response the app displays to the agent user.

    Assembled by the orchestrator from the individual agent outputs.
    Maintains backward compatibility with the original single-agent schema.
    """

    # Drafting outputs
    internal_note: str = Field(description="Markdown internal note following the Identification → Assessment → Resolution schema.")
    player_reply: str = Field(description="Ready-to-paste public reply. Follows the Communication handbook tone rules.")
    next_steps: list[str] = Field(description="Ordered investigation/action items for the human agent to perform.")
    missing_info: list[str] = Field(default_factory=list, description="Questions to ask the player if information is missing.")

    # Citations (merged from all drafting agents)
    citations: list[Citation] = Field(default_factory=list, description="SOP sections the draft relied on.")

    # Safety outputs
    escalation_flag: bool = Field(default=False)
    escalation_reason: str = Field(default="")

    # Aggregate confidence (lowest of the three drafting agents)
    confidence: Literal["low", "medium", "high"] = "medium"

    # Meta
    notes_for_agent: str = Field(default="", description="Short meta note to the human agent.")
