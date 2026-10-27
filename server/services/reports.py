"""Reporting: support KPIs computed from tickets, AI runs, events and article feedback.

Computed in Python over the selected window. Fine at prototype scale; a real
deployment would precompute daily rollups or push events to a warehouse.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from ..db import utcnow
from ..kb import get_catalog
from ..models import AiRun, ArticleView, Message, Ticket, TicketStatus

RESOLVED = (TicketStatus.solved, TicketStatus.closed)


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _seconds(a: datetime | None, b: datetime | None) -> float | None:
    return (b - a).total_seconds() if a and b else None


def _kpis(session: Session, start: datetime, end: datetime) -> dict:
    tickets = session.exec(select(Ticket).where(Ticket.created_at >= start, Ticket.created_at < end)).all()
    resolved = [t for t in tickets if t.status in RESOLVED and t.resolved_by]
    by = Counter(t.resolved_by for t in resolved)
    handed_off = [t for t in tickets if t.handoff_reason]
    first_ai = [s for t in tickets if (s := _seconds(t.created_at, t.first_response_at)) is not None]
    first_human = [s for t in tickets if (s := _seconds(t.created_at, t.first_human_response_at)) is not None]
    resolution_h = [s / 3600 for t in resolved if (s := _seconds(t.created_at, t.solved_at)) is not None]
    csat = [t.csat for t in tickets if t.csat]
    views = session.exec(select(ArticleView).where(ArticleView.at >= start, ArticleView.at < end)).all()
    return {
        "tickets": len(tickets),
        "resolved": len(resolved),
        # Share of resolved tickets the AI closed out with no human reply (player confirmed).
        "ai_resolution_rate": _rate(by["ai"], len(resolved)),
        "resolved_by": {"ai": by["ai"], "agent": by["agent"], "auto": by["auto"]},
        "handoff_rate": _rate(len(handed_off), len(tickets)),
        "escalations": sum(1 for t in tickets if t.escalated),
        "deflections": sum(1 for v in views if v.helpful),
        "article_feedback": len(views),
        "median_first_response_s": _median(first_ai),
        "median_first_human_response_h": _median([s / 3600 for s in first_human]),
        "median_resolution_h": _median(resolution_h),
        "csat_avg": round(sum(csat) / len(csat), 2) if csat else None,
        "csat_count": len(csat),
        "_tickets": tickets,
        "_views": views,
    }


def build_report(session: Session, days: int) -> dict:
    now = utcnow()
    start = now - timedelta(days=days)
    cur = _kpis(session, start, now)
    prev = _kpis(session, start - timedelta(days=days), start)
    tickets: list[Ticket] = cur.pop("_tickets")
    views: list[ArticleView] = cur.pop("_views")
    prev.pop("_tickets")
    prev.pop("_views")

    # Daily volume and how each day's tickets ended up.
    day_rows: dict[str, dict] = {}
    for i in range(days):
        d = (start + timedelta(days=i + 1)).date().isoformat()
        day_rows[d] = {"date": d, "created": 0, "ai": 0, "agent": 0, "auto": 0, "open": 0}
    for t in tickets:
        row = day_rows.get(t.created_at.date().isoformat())
        if row is None:
            continue
        row["created"] += 1
        if t.status in RESOLVED and t.resolved_by in ("ai", "agent", "auto"):
            row[t.resolved_by] += 1
        else:
            row["open"] += 1

    # Topics, with AI resolution and confidence per topic.
    ids = [t.id for t in tickets]
    runs = (
        session.exec(select(AiRun).where(col(AiRun.ticket_id).in_(ids), AiRun.status == "succeeded")).all() if ids else []
    )
    intake = {r.ticket_id: r for r in runs if r.trigger == "intake"}
    topic_stats: dict[str, dict] = defaultdict(lambda: {"tickets": 0, "ai": 0, "resolved": 0, "low_conf": 0, "no_cite": 0, "csat": []})
    for t in tickets:
        ts = topic_stats[t.topic or "uncategorized"]
        ts["tickets"] += 1
        if t.status in RESOLVED and t.resolved_by:
            ts["resolved"] += 1
            ts["ai"] += t.resolved_by == "ai"
        if t.csat:
            ts["csat"].append(t.csat)
        run = intake.get(t.id)
        if run:
            out = run.result.get("output", {})
            ts["low_conf"] += out.get("confidence") == "low"
            ts["no_cite"] += not out.get("citations")
    topics = sorted(
        (
            {
                "topic": k,
                "tickets": v["tickets"],
                "ai_resolution_rate": _rate(v["ai"], v["resolved"]),
                "low_confidence_rate": _rate(v["low_conf"], v["tickets"]),
                "csat_avg": round(sum(v["csat"]) / len(v["csat"]), 2) if v["csat"] else None,
            }
            for k, v in topic_stats.items()
        ),
        key=lambda r: r["tickets"],
        reverse=True,
    )
    # Knowledge gaps: topics where the AI often lacked a good article.
    kb_gaps = [
        {**t, "no_citation": topic_stats[t["topic"]]["no_cite"]}
        for t in topics
        if t["tickets"] >= 3 and (t["low_confidence_rate"] or 0) >= 0.3
    ]

    # Waiting on players: how long they've been waiting.
    pending = session.exec(select(Ticket).where(Ticket.status == TicketStatus.pending)).all()
    buckets = {"< 1 day": 0, "1–3 days": 0, "3–7 days": 0, "> 7 days": 0}
    for t in pending:
        age_d = (now - (t.pending_since or t.updated_at)).total_seconds() / 86400
        key = "< 1 day" if age_d < 1 else "1–3 days" if age_d < 3 else "3–7 days" if age_d < 7 else "> 7 days"
        buckets[key] += 1

    backlog = {
        s.value: n
        for s in (TicketStatus.new, TicketStatus.open, TicketStatus.pending, TicketStatus.on_hold)
        if (n := len(session.exec(select(Ticket.id).where(Ticket.status == s)).all()))
    }

    handoffs = Counter(t.handoff_reason for t in tickets if t.handoff_reason)

    # QA and latency from player-facing runs.
    player_runs = [r for r in runs if r.trigger != "agent_draft"]
    qa_final = [r.result.get("qa", [])[-1] for r in player_runs if r.result.get("qa")]
    crit_fail = sum(1 for q in qa_final if any(not c["passed"] and c["severity"] == "critical" for c in q.get("checks", [])))
    stage_lat: dict[str, list[float]] = defaultdict(list)
    for r in player_runs:
        tm = r.result.get("timings", {})
        for k in ("classifier", "retrieval", "safety", "drafting"):
            if isinstance(tm.get(k), int | float):
                stage_lat[k].append(tm[k])
        if tm.get("qa"):
            stage_lat["qa"].append(sum(tm["qa"]))
        if r.duration_s:
            stage_lat["total"].append(r.duration_s)

    # Most-cited public articles: number of tickets whose AI answers cited each one.
    catalog = get_catalog()
    msgs = (
        session.exec(
            select(Message.ticket_id, Message.citations).where(col(Message.ticket_id).in_(ids), Message.author_kind == "ai")
        ).all()
        if ids
        else []
    )
    cited_pairs = {(tid, c["slug"]) for tid, cites in msgs for c in cites or []}
    cite_counts: Counter = Counter(slug for _, slug in cited_pairs)
    top_articles = [
        {"slug": s, "title": a.title if (a := catalog.public_article(s)) else s, "citations": n}
        for s, n in cite_counts.most_common(6)
    ]
    helpful_by_slug = Counter(v.slug for v in views if v.helpful)

    return {
        "range": {"days": days, "from": start.isoformat(), "to": now.isoformat()},
        "has_demo_data": any(t.demo for t in tickets),
        "kpis": cur,
        "previous": prev,
        "volume": list(day_rows.values()),
        "topics": topics,
        "kb_gaps": kb_gaps,
        "handoff_reasons": dict(handoffs),
        "pending_aging": [{"bucket": k, "count": v} for k, v in buckets.items()],
        "backlog": backlog,
        "csat_distribution": [{"rating": i, "count": sum(1 for t in tickets if t.csat == i)} for i in range(1, 6)],
        "qa": {
            "runs": len(qa_final),
            "pass_rate": _rate(sum(1 for q in qa_final if q.get("passed")), len(qa_final)),
            "avg_score": round(sum(q.get("overall_score", 0) for q in qa_final) / len(qa_final), 3) if qa_final else None,
            "critical_fail_rate": _rate(crit_fail, len(qa_final)),
        },
        "latency": {k: _median(v) for k, v in stage_lat.items()},
        "top_articles": top_articles,
        "deflection_articles": [
            {"slug": s, "title": a.title if (a := catalog.public_article(s)) else s, "helpful": n}
            for s, n in helpful_by_slug.most_common(5)
        ],
    }
