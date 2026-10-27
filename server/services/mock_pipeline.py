"""Mock pipeline: realistic, KB-grounded answers with zero LLM/API calls.

Used for local demos, frontend work and tests (PIPELINE_MODE=mock, the
default). It walks the same stages as the live pipeline with short delays, and
uses simple keyword rules for classification and safety, so every routing path
(answer, checklist, low confidence, escalation, self-harm) can be exercised:

  "error 105 crossplay"             → answered from the help article
  "recover my account"              → asks for the NovaStar ID (checklist)
  "lawyer" / "sue"                  → legal escalation (holding reply)
  "hurt myself"                     → self-harm escalation (crisis resources)
  anything with no matching article → low-confidence answer, flagged for review
"""

from __future__ import annotations

import re
import time

from src.schemas import (
    AgentOutput,
    Citation,
    ClassifierOutput,
    PIIItem,
    QACheck,
    QAResult,
    SafetyOutput,
)

from ..kb import Article, SectionHit, get_catalog
from ..settings import settings
from .pipeline import HitSummary, Persona, PipelineResult, StageCallback

NOVASTAR_ID_RE = re.compile(r"\bEVD(?:-[A-Z0-9]{4}){2,3}\b", re.IGNORECASE)
PLATFORM_RE = {
    "PC": re.compile(r"\b(pc|steam|windows|epic)\b", re.I),
    "PlayStation": re.compile(r"\b(ps4|ps5|playstation|psn)\b", re.I),
    "Xbox": re.compile(r"\b(xbox|series [xs])\b", re.I),
    "Switch": re.compile(r"\b(switch|nintendo)\b", re.I),
}
TOPICS = (
    ("disconnect_penalty", re.compile(r"\b(penalt\w*|cooldown)\b", re.I)),
    ("matchmaking_error", re.compile(r"\b(error\s*105|matchmak\w*|queue)\b", re.I)),
    ("purchases", re.compile(r"\b(bought|purchas\w*|charged|refund\w*|bundle|starshards|season pass|rewards?|skins?)\b", re.I)),
    ("account_recovery", re.compile(r"\b(recover\w*|hacked|password|email|link\w*|login|log in|sign in)\b", re.I)),
    ("connection", re.compile(r"\b(disconnect\w*|lag\w*|ping|latency|timeout|timed out|kicked)\b", re.I)),
    ("player_report", re.compile(r"\b(cheat\w*|hacker|harass\w*|toxic|report\w*|offensive)\b", re.I)),
)
SELF_HARM_RE = re.compile(r"\b(kill myself|hurt myself|end my life|suicid\w*|self[- ]harm)\b", re.I)
VIOLENCE_RE = re.compile(r"\b(i('| a)?m going to (kill|hurt|shoot)|bomb|shoot up)\b", re.I)
LEGAL_RE = re.compile(r"\b(lawyer|attorney|sue|lawsuit|legal action|small claims)\b", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
PASSWORD_RE = re.compile(r"\bpassword\s*(is|:)\s*\S+", re.I)
MIN_ANSWER_SCORE = 3.0
WHEN_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\byesterday\b|\btoday\b|\blast night\b|\b\d{1,2}[/-]\d{1,2}\b", re.I)


def _sleep(fast: bool = False) -> None:
    if settings.mock_stage_delay > 0 and not fast:
        time.sleep(settings.mock_stage_delay)


def _classify(text: str) -> ClassifierOutput:
    topic = next((name for name, rx in TOPICS if rx.search(text)), "general_inquiry")
    return ClassifierOutput(
        primary_topic=topic,
        platforms=[name for name, rx in PLATFORM_RE.items() if rx.search(text)],
        suspected_category="game",
        urgency="high" if topic == "account_recovery" else "medium",
        is_bug_report=topic == "matchmaking_error",
        is_ban_related=topic == "disconnect_penalty",
        player_language="en",
        extracted_ids=[m.upper() for m in NOVASTAR_ID_RE.findall(text)],
        search_queries=[text[:80]],
    )


def _safety(text: str) -> SafetyOutput:
    pii: list[PIIItem] = []
    if PHONE_RE.search(text):
        pii.append(PIIItem(pii_type="phone_number", location="ticket body", must_redact=True))
    if PASSWORD_RE.search(text):
        pii.append(PIIItem(pii_type="password", location="ticket body", must_redact=True))
    if SELF_HARM_RE.search(text):
        threat, reason, urgent = "rlt_self_harm", "Player expressed thoughts of self-harm.", True
    elif VIOLENCE_RE.search(text):
        threat, reason, urgent = "rlt_violence", "Ticket contains a threat of violence.", True
    elif LEGAL_RE.search(text):
        threat, reason, urgent = "legal", "Player mentions legal action.", False
    else:
        threat, reason, urgent = "none", "", False
    flagged = threat != "none"
    return SafetyOutput(
        pii_detected=pii,
        must_redact=any(p.must_redact for p in pii),
        escalation_flag=flagged,
        escalation_reason=reason,
        escalation_target="Support Leadership" if flagged else "",
        threat_type=threat,
        threat_is_urgent=urgent,
        detected_language="en",
        safety_notes="Redact PII before replying." if pii else "",
    )


def _list_items(text: str) -> list[str]:
    return [m.strip() for m in re.findall(r"^\s*(?:\d+\.|-)\s+(.+)$", text, re.M)]


def _section(article: Article, *names: str):
    for name in names:
        for s in article.sections:
            if name.lower() in s.heading.lower():
                return s
    return article.sections[0] if article.sections else None


def _missing_info(cls: ClassifierOutput, text: str) -> list[str]:
    items: list[str] = []
    if cls.primary_topic == "account_recovery" and not cls.extracted_ids:
        items.append("Share your NovaStar ID (format EVD-XXXX-XXXX-XXXX). It's under Settings > Account in the game.")
    if cls.primary_topic in ("connection", "matchmaking_error", "disconnect_penalty") and not cls.platforms:
        items.append("Tell us which platform you play on (PC, PlayStation, Xbox or Switch).")
    if cls.primary_topic == "disconnect_penalty" and not WHEN_RE.search(text):
        items.append("Tell us roughly when the disconnect happened (date, time and time zone).")
    return items


SIGNER_RE = re.compile(r"Sign the reply as ([^.\n]+)\.")


def _compose_reply(persona: Persona, safety: SafetyOutput, hit: SectionHit | None, missing: list[str], guidance: str = "") -> str:
    article = hit.article if hit else None
    signer = m.group(1).strip() if (m := SIGNER_RE.search(guidance)) else "Alex"
    if persona == "ai_assistant":
        opening = "Hi,\n\nI'm the Everdawn Support Assistant, an AI helper for the Everdawn team."
        closing = "Best regards,\nEverdawn Support Assistant"
        handoff = 'You can reply here at any time, or choose "I still need help" to reach a member of the team.'
    else:
        opening = f"Hello,\n\nThis is {signer} from the Everdawn team,"
        closing = f"Best regards,\n{signer}"
        handoff = ""

    if safety.escalation_flag:
        if safety.threat_type == "rlt_self_harm":
            body = (
                "Thank you for telling us how you're feeling. You matter, and you don't have to go "
                "through this alone. If you are in immediate danger, please contact your local "
                "emergency services now. You can also reach a crisis line in your country at any "
                "time, day or night.\n\nA member of our team will read your message personally."
            )
        else:
            body = (
                "Thank you for reaching out and for telling us about this. I've passed your ticket "
                "to a member of our team, who will review it personally and reply here."
            )
        return "\n\n".join((opening, body, closing))

    parts = [opening]
    if article:
        # Prefer the section that actually matched the ticket, if it has steps to follow.
        sec = hit.section if _list_items(hit.section.text) else _section(
            article, "workaround", "quick fixes", "where to find", "report in game", "server-side"
        )
        steps = _list_items(sec.text) if sec else []
        parts.append(f'Thanks for getting in touch. This looks like the issue covered in our article "{article.title}".')
        if steps:
            numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(steps[:5], start=1))
            parts.append(f"**{sec.heading}**\n\n{numbered}")
        elif sec:
            parts.append(sec.text)
    else:
        parts.append(
            "Thanks for getting in touch. I couldn't find a help article that matches this exactly, "
            "so I've noted the details for our team."
        )
    if missing:
        parts.append("To look into this further, could you help me with the following?\n\n" + "\n".join(f"- {m}" for m in missing))
    if handoff:
        parts.append(handoff)
    parts.append(closing)
    return "\n\n".join(parts)


def _hit_summary(h: SectionHit) -> HitSummary:
    return HitSummary(
        chunk_id=f"{h.article.id}::{h.section.heading}",
        article_id=h.article.id,
        title=h.article.title,
        heading=h.section.heading,
        type=h.article.type,
        audience=h.article.audience,
        score=round(h.score, 3),
        source="lexical",
    )


def run_mock(
    ticket: str,
    *,
    images: list[bytes],
    guidance: str,
    persona: Persona,
    on_stage: StageCallback,
    fast: bool = False,
) -> PipelineResult:
    """`fast` skips the simulated stage delays (used by the demo seeder)."""
    timings: dict = {"vision": 0.0}
    screenshot_text = ""
    if images:
        on_stage("vision", f"Reading {len(images)} screenshot(s)...")
        t0 = time.perf_counter()
        _sleep(fast)
        screenshot_text = f"[mock] {len(images)} screenshot(s) attached; transcription runs in live mode."
        timings["vision"] = time.perf_counter() - t0

    on_stage("classify", "Classifying ticket...")
    t0 = time.perf_counter()
    _sleep(fast)
    cls = _classify(ticket)
    timings["classifier"] = time.perf_counter() - t0

    on_stage("retrieve", "Retrieving SOP context and running safety analysis...")
    t0 = time.perf_counter()
    _sleep(fast)
    hits = get_catalog().search_sections(ticket, limit=6)
    safety = _safety(ticket)
    timings["retrieval"] = timings["safety"] = time.perf_counter() - t0

    on_stage("draft", "Drafting note, reply, and steps in parallel...")
    t0 = time.perf_counter()
    _sleep(fast)
    # Weak lexical matches don't count as "the KB covers this" (keeps confidence honest).
    public_hit = next((h for h in hits if h.article.is_public and h.score >= MIN_ANSWER_SCORE), None)
    internal_hit = next((h for h in hits if not h.article.is_public and h.score >= MIN_ANSWER_SCORE), None)
    article = public_hit.article if public_hit else None
    missing = [] if safety.escalation_flag else _missing_info(cls, ticket)
    reply = _compose_reply(persona, safety, public_hit, missing, guidance)

    citations = [
        Citation(article=h.article.title, section=h.section.heading, article_id=h.article.id, source_url=h.article.source_url)
        for h in (public_hit, internal_hit)
        if h
    ]
    inv = _section(internal_hit.article, "investigation") if internal_hit else None
    next_steps = (_list_items(inv.text) if inv else [])[:5] or ["Review the ticket and reply to the player personally."]
    if safety.escalation_flag:
        # Escalations get escalation steps only; normal troubleshooting is irrelevant here.
        next_steps = [
            f"Escalate to {safety.escalation_target}: {safety.escalation_reason}",
            "Read the full thread before replying; the AI has only sent a holding message.",
            "Reply personally. Don't promise an outcome until the escalation owner confirms.",
        ]
    note = "\n".join(
        [
            "**Identification**",
            f"- Customer ID: {', '.join(cls.extracted_ids) or '(pending)'}",
            f"- Platform: {', '.join(cls.platforms) or '(pending)'}",
            "",
            "**Assessment**",
            f"- Summary: {' '.join(ticket.split())[:200]}",
            f"- Topic: {cls.primary_topic}",
            f"- Matched documentation: {', '.join(c.article for c in citations) or 'none'}",
            "",
            "**Resolution**",
            f"- Actions taken: {'AI holding reply sent' if safety.escalation_flag else 'AI answer sent'}",
            f"- PII status: {'redaction required' if safety.must_redact else 'no PII requiring redaction'}",
            f"- Escalation: {safety.escalation_target or 'none'}",
        ]
    )
    if safety.escalation_flag:
        confidence = "medium"
    elif article and public_hit.score > 2:
        confidence = "high"
    else:
        confidence = "medium" if article else "low"
    timings["drafting"] = time.perf_counter() - t0

    on_stage("qa", "QA validation...")
    t0 = time.perf_counter()
    _sleep(fast)
    qa_pass = confidence != "low"
    qa = QAResult(
        overall_score=0.94 if qa_pass else 0.71,
        passed=qa_pass,
        checks=[
            QACheck(rule_id="agent_intro_line", category="tone", severity="major", passed=True),
            QACheck(rule_id="no_invented_procedures", category="hard_rule", severity="critical", passed=True),
            QACheck(rule_id="pii_not_echoed", category="hard_rule", severity="critical", passed=True),
            QACheck(
                rule_id="citations_present",
                category="citations",
                severity="major",
                passed=bool(citations),
                detail="" if citations else "No KB article supports this reply.",
            ),
        ],
        qa_agent_notes="" if qa_pass else "No matching article; a human should double-check this answer.",
    )
    timings["qa"] = [time.perf_counter() - t0]

    return PipelineResult(
        mode="mock",
        persona=persona,
        output=AgentOutput(
            internal_note=note,
            player_reply=reply,
            next_steps=next_steps,
            missing_info=missing,
            citations=citations,
            escalation_flag=safety.escalation_flag,
            escalation_reason=safety.escalation_reason,
            confidence=confidence,
            notes_for_agent=f"Agent guidance applied: {guidance}" if guidance.strip() else "",
        ),
        classification=cls,
        safety=safety,
        qa=[qa],
        hits=[_hit_summary(h) for h in hits],
        timings=timings,
        screenshot_text=screenshot_text,
        note_confidence=confidence,
        reply_confidence=confidence,
        steps_confidence="medium" if internal_hit else "low",
    )
