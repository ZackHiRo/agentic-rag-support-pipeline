"""Reply-routing engine: decides what happens to a ticket after an AI run.

Pure function, no I/O, so the policy is easy to read and unit-test.

The AI is autonomous: on intake and on player follow-ups it always replies.
What changes is the status and whether people need to look at it:

  safety flag (escalation / threat)  → holding reply, open, high/urgent, needs a human
                                       (+ crisis resources for self-harm signals)
  needs something from the player    → answer + checklist, pending
  low confidence or failed QA        → answer, pending, flagged for staff review
  otherwise                          → answer, pending (awaiting "That fixed it")

Staff-requested drafts (agent_draft) are never sent; they land in the console.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

URGENT_THREATS = frozenset({"rlt_self_harm", "rlt_violence"})


@dataclass(frozen=True)
class RunSignals:
    trigger: str  # intake | player_reply | agent_draft
    escalation_flag: bool = False
    threat_type: str = "none"
    threat_is_urgent: bool = False
    missing_info: tuple[str, ...] = ()
    qa_passed: bool | None = None
    confidence: str = "medium"  # low | medium | high


@dataclass(frozen=True)
class Decision:
    kind: str  # escalated | needs_info | low_confidence | answered | draft
    send_to_player: bool
    status: str | None  # new ticket status, None = leave unchanged
    priority: str | None = None  # None = leave unchanged
    needs_human: bool = False
    handoff_reason: str | None = None
    needs_review: bool = False
    crisis_resources: bool = False
    action_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def decide(sig: RunSignals) -> Decision:
    if sig.trigger == "agent_draft":
        return Decision(kind="draft", send_to_player=False, status=None)

    if sig.escalation_flag or sig.threat_type != "none":
        urgent = sig.threat_is_urgent or sig.threat_type in URGENT_THREATS
        return Decision(
            kind="escalated",
            send_to_player=True,
            status="open",
            priority="urgent" if urgent else "high",
            needs_human=True,
            handoff_reason="safety",
            crisis_resources=sig.threat_type == "rlt_self_harm",
        )

    low_confidence = sig.qa_passed is False or sig.confidence == "low"
    items = [m.strip() for m in sig.missing_info if m and m.strip()]
    if items:
        return Decision(
            kind="needs_info",
            send_to_player=True,
            status="pending",
            needs_review=low_confidence,
            action_items=items,
        )
    if low_confidence:
        return Decision(kind="low_confidence", send_to_player=True, status="pending", needs_review=True)
    return Decision(kind="answered", send_to_player=True, status="pending")
