"""Seed realistic demo data so the console and reporting look alive on a fresh clone.

    python -m server.seed                    # 300 tickets over the last 60 days
    python -m server.seed --tickets 500 --days 90
    python -m server.seed --reset            # remove all demo data (and nothing else)
    python -m server.seed --if-empty         # seed only if there is no demo data yet

Every ticket is replayed through the real domain logic (mock pipeline,
routing policy, status transitions) with the clock frozen at each historical
moment, so seeded data has the same shape as real data. No LLM calls are made.
All rows are marked demo=True.
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta

from sqlmodel import Session, col, delete, select

from .auth import ensure_demo_staff
from .db import engine, frozen_clock, init_db, utcnow
from .models import (
    ActionRequest,
    AiRun,
    ArticleView,
    Attachment,
    AuthorKind,
    Message,
    RunStatus,
    Ticket,
    TicketEvent,
    TicketStatus,
    User,
)
from .services.mock_pipeline import run_mock
from .services.routing import RunSignals, decide
from .services.tickets import add_message, apply_ai_result, compose_conversation, log_event, make_ref, set_status, subject_from

FIRST = "Riley Sam Jordan Alex Casey Morgan Taylor Jamie Avery Quinn Rowan Skyler Emery Hayden Kai Noa Sasha Remy Ari Jules".split()
LAST = "K. M. R. T. L. P. S. D. V. B. N. H. C. F. G. W.".split()
PLATFORMS = ["PC", "PlayStation", "Xbox", "Switch"]

# topic → (weight, ticket texts). Mock classification derives the topic from the text.
SCENARIOS: dict[str, tuple[float, list[str]]] = {
    "matchmaking_error": (0.22, [
        "Matchmaking Error 105 every time I queue with my friend on {other}.",
        "Can't queue as a party, keeps saying error 105. We're on PC and {other}.",
        "Error 105 when entering matchmaking with my crossplay group",
        "My squad gets kicked out of the queue with error 105",
    ]),
    "connection": (0.2, [
        "I keep getting disconnected mid match, my ping spikes to 300.",
        "Constant lag and timeouts since the last update on {platform}.",
        "Got disconnected three times tonight, internet is fine otherwise.",
        "Timed out of every match this evening, other games work fine.",
    ]),
    "account_recovery": (0.17, [
        "I lost access to my email and need to recover my account.",
        "Can't log in anymore, I think my account got hacked.",
        "How do I link my Steam account to my NovaStar account?",
        "I changed phones and can't sign in, need to recover my account EVD-{id}.",
    ]),
    "disconnect_penalty": (0.15, [
        "I got a matchmaking penalty after the server crashed yesterday at 9pm.",
        "Unfair penalty, the game crashed and now I have a cooldown.",
        "Why do I have a penalty? The server kicked everyone out.",
    ]),
    "player_report": (0.12, [
        "Someone was cheating in my last match, wall hacks for sure.",
        "A player kept harassing me in chat, I want to report them.",
        "Reporting a player with an offensive name.",
    ]),
    # No help article covers purchases: the AI answers with low confidence,
    # which is exactly what the "knowledge gaps" report should surface.
    "purchases": (0.11, [
        "I bought the Dawnbreaker bundle but the skins never showed up in my inventory.",
        "Charged twice for Starshards, only received one pack.",
        "My season pass rewards disappeared after the patch.",
    ]),
    "general_inquiry": (0.03, [
        "Is there going to be a Switch 2 version?",
        "Do you have a bug bounty program?",
    ]),
}
# Legal threats only: crisis (self-harm) handling is covered by tests, not by demo data.
ESCALATIONS = [
    "This is the third time I've been charged. I'm talking to my lawyer and will sue if this isn't fixed.",
    "You banned me for no reason. My attorney will be in touch about legal action.",
]
FOLLOWUPS_FAIL = ["Tried all of that, still happening.", "That didn't work, same problem.", "No luck, it's still broken."]
AGENT_REPLIES = [
    "Thanks for your patience. I've looked into this with the team and applied a fix on our side. Could you try again and let me know?",
    "Sorry for the trouble. I've escalated this internally and credited your account. Let me know if anything else comes up.",
    "Thanks for the details. I checked our server logs and removed the penalty from your account.",
]


def _player(session: Session, rng: random.Random, pool: list[User]) -> User:
    if pool and rng.random() < 0.35:
        return rng.choice(pool)  # returning players
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    email = f"{name.split()[0].lower()}.{rng.randrange(10_000):04d}@example.com"
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(email=email, display_name=name, demo=True, created_at=utcnow())
        session.add(user)
        session.flush()
    pool.append(user)
    return user


def _run_ai(session: Session, ticket: Ticket, trigger: str, rng: random.Random) -> None:
    """Replay one AI run with realistic live-mode timings."""
    text = compose_conversation(session, ticket)
    result = run_mock(text, images=[], guidance="", persona="ai_assistant", on_stage=lambda *_: None, fast=True)
    t = {"vision": 0.0, "classifier": rng.uniform(0.8, 2.0), "retrieval": rng.uniform(0.5, 1.6), "drafting": rng.uniform(7, 16)}
    t["safety"] = rng.uniform(1.0, 2.5)
    t["qa"] = [rng.uniform(3, 7)] + ([rng.uniform(3, 6)] if rng.random() < 0.12 else [])
    result.timings = t
    duration = t["classifier"] + max(t["retrieval"], t["safety"]) + t["drafting"] + sum(t["qa"]) + rng.uniform(0.3, 1.2)
    now = utcnow()
    run = AiRun(
        ticket_id=ticket.id, trigger=trigger, persona="ai_assistant", mode="mock", status=RunStatus.succeeded,
        stages=[{"key": k, "label": k, "at": now.isoformat()} for k in ("classify", "retrieve", "draft", "qa")],
        created_at=now - timedelta(seconds=duration), started_at=now - timedelta(seconds=duration),
        finished_at=now, duration_s=round(duration, 2),
    )
    session.add(run)
    session.flush()
    safety = result.safety
    decision = decide(
        RunSignals(
            trigger=trigger, escalation_flag=safety.escalation_flag, threat_type=safety.threat_type,
            threat_is_urgent=safety.threat_is_urgent, missing_info=tuple(result.output.missing_info),
            qa_passed=result.qa_passed, confidence=result.output.confidence,
        )
    )
    apply_ai_result(session, ticket, run, result, decision)


def _resolve(session: Session, ticket: Ticket, by: str, rng: random.Random, csat_bias: float) -> None:
    ticket.resolved_by = by
    set_status(session, ticket, TicketStatus.solved, actor_kind="player" if by == "ai" else "agent", reason="seed")
    if by != "auto" and rng.random() < 0.55:
        ticket.csat = max(1, min(5, round(rng.gauss(csat_bias, 0.8))))
        log_event(session, ticket, "csat.submitted", actor_kind="player", rating=ticket.csat)


def _seed_ticket(session: Session, rng: random.Random, at: datetime, now: datetime, players: list[User], staff: list[User]) -> None:
    player = _player(session, rng, players)
    if rng.random() < 0.015 or (now - at < timedelta(days=1) and rng.random() < 0.08):
        text, topic = rng.choice(ESCALATIONS), "escalation"
    else:
        topic = rng.choices(list(SCENARIOS), weights=[w for w, _ in SCENARIOS.values()])[0]
        text = rng.choice(SCENARIOS[topic][1]).format(
            other=rng.choice(PLATFORMS[1:]), platform=rng.choice(PLATFORMS), id=f"{rng.randrange(10**4):04d}-AB{rng.randrange(10):d}C-{rng.randrange(10**4):04d}"
        )
    platform = rng.choice(PLATFORMS) if rng.random() < 0.6 else ""

    def clock(dt: datetime):
        return frozen_clock(min(dt, now))

    with clock(at):
        ticket = Ticket(requester_id=player.id, subject=subject_from(text), platform=platform, status=TicketStatus.new, demo=True)
        session.add(ticket)
        session.flush()
        ticket.ref = make_ref(ticket.id)
        add_message(session, ticket, author_kind=AuthorKind.player, author_id=player.id, body=text)
        log_event(session, ticket, "ticket.created", actor_kind="player", actor_id=player.id)
        session.flush()
    t = at + timedelta(seconds=rng.uniform(12, 50))
    with clock(t):
        _run_ai(session, ticket, "intake", rng)

    def later(lo_h: float, hi_h: float) -> datetime:
        nonlocal t
        t = t + timedelta(hours=rng.uniform(lo_h, hi_h))
        return t

    def agent_handles(reason_text: str | None) -> None:
        nonlocal t
        agent = rng.choice(staff)
        if reason_text:
            with clock(later(0.1, 20)):
                add_message(session, ticket, author_kind=AuthorKind.player, author_id=player.id, body=reason_text)
                ticket.needs_human, ticket.handoff_reason = True, ticket.handoff_reason or "player_request"
                add_message(session, ticket, author_kind=AuthorKind.system, body="Thanks for letting us know. A member of the Everdawn team will take it from here and reply in this ticket.")
                set_status(session, ticket, TicketStatus.open, actor_kind="player", reason="player_request")
        if later(0.3, 9) > now or (now - t < timedelta(days=2) and rng.random() < 0.5):
            return  # still waiting for an agent: shows up in the queue
        with clock(t):
            add_message(session, ticket, author_kind=AuthorKind.agent, author_id=agent.id, body=rng.choice(AGENT_REPLIES))
            ticket.assignee_id = agent.id
            ticket.first_human_response_at = ticket.first_human_response_at or t
            if rng.random() < 0.12:
                set_status(session, ticket, TicketStatus.on_hold, actor_kind="agent", actor_id=agent.id)
                return
            set_status(session, ticket, TicketStatus.pending, actor_kind="agent", actor_id=agent.id)
        if later(1, 30) > now:
            return
        with clock(t):
            _resolve(session, ticket, "agent", rng, csat_bias=4.1)

    # Escalations go straight to people.
    if ticket.escalated:
        agent_handles(None)
    else:
        # Complete any checklist the AI asked for, then the AI answers again.
        open_items = session.exec(select(ActionRequest).where(ActionRequest.ticket_id == ticket.id, ActionRequest.done == False)).all()  # noqa: E712
        if open_items and rng.random() < 0.75 and later(0.2, 30) < now:
            with clock(t):
                for a in open_items:
                    a.done, a.completed_at = True, t
                    a.response = f"EVD-{rng.randrange(10**4):04d}-{rng.randrange(10**4):04d}-{rng.randrange(10**4):04d}" if "ID" in a.text else rng.choice(PLATFORMS)
                    add_message(session, ticket, author_kind=AuthorKind.player, author_id=player.id, body=f"✓ {a.text}\n{a.response}")
                set_status(session, ticket, TicketStatus.new, actor_kind="player", reason="checklist_completed")
            with clock(later(0.005, 0.02)):
                _run_ai(session, ticket, "player_reply", rng)

        low_conf = ticket.needs_review
        roll = rng.random()
        recent = now - at < timedelta(days=2)
        p_fixed = 0.25 if low_conf else (0.5 if recent else 0.64)
        p_handoff = 0.55 if low_conf else (0.3 if recent else 0.16)
        if ticket.status == TicketStatus.pending and not session.exec(
            select(ActionRequest.id).where(ActionRequest.ticket_id == ticket.id, ActionRequest.done == False)  # noqa: E712
        ).first():
            if roll < p_fixed:
                if later(0.05, 18) < now:
                    with clock(t):
                        _resolve(session, ticket, "ai", rng, csat_bias=4.4)
            elif roll < p_fixed + p_handoff:
                agent_handles(rng.choice(FOLLOWUPS_FAIL))
            # else: the player went quiet; the lifecycle rules below auto-solve it.

    # Lifecycle: auto-solve quiet pending tickets, close old solved ones.
    if ticket.status == TicketStatus.pending and ticket.pending_since and ticket.pending_since + timedelta(days=7) < now:
        with clock(ticket.pending_since + timedelta(days=7, minutes=5)):
            _resolve(session, ticket, "auto", rng, csat_bias=0)
    if ticket.status == TicketStatus.solved and ticket.solved_at and ticket.solved_at + timedelta(days=4) < now:
        with clock(ticket.solved_at + timedelta(days=4, minutes=5)):
            set_status(session, ticket, TicketStatus.closed, reason="auto_close")


def _seed_article_views(session: Session, rng: random.Random, days: int, n_tickets: int, now: datetime) -> None:
    slugs = ["matchmaking-error-105", "fix-connection-issues", "find-your-player-id", "account-recovery-and-linking", "disconnect-penalties", "report-a-player"]
    weights = [0.3, 0.25, 0.15, 0.12, 0.1, 0.08]
    for _ in range(int(n_tickets * 0.8)):
        at = now - timedelta(days=rng.uniform(0, days))
        session.add(ArticleView(slug=rng.choices(slugs, weights)[0], helpful=rng.random() < 0.62, at=at, demo=True))


def reset_demo(session: Session) -> int:
    ids = list(session.exec(select(Ticket.id).where(Ticket.demo == True)).all())  # noqa: E712
    for model in (TicketEvent, ActionRequest, Attachment, Message, AiRun):
        session.exec(delete(model).where(col(model.ticket_id).in_(ids)))
    session.exec(delete(Ticket).where(col(Ticket.id).in_(ids)))
    session.exec(delete(ArticleView).where(ArticleView.demo == True))  # noqa: E712
    session.exec(delete(User).where(User.demo == True))  # noqa: E712
    session.commit()
    return len(ids)


def seed(tickets: int = 300, days: int = 60, seed_value: int = 7) -> None:
    rng = random.Random(seed_value)
    now = utcnow()
    with Session(engine) as session:
        ensure_demo_staff(session)
        staff = list(session.exec(select(User).where(col(User.role).in_(["agent", "admin"]))).all())
        players: list[User] = []
        # Ticket arrivals: steady growth with weekly rhythm, slightly busier on weekends.
        times = []
        for _ in range(tickets):
            d = days * rng.random() ** 1.25  # volume grows toward today
            at = now - timedelta(days=d)
            if at.weekday() >= 5 and rng.random() < 0.3:
                at -= timedelta(hours=rng.uniform(0, 6))
            times.append(at)
        for i, at in enumerate(sorted(times)):
            _seed_ticket(session, rng, at, now, players, staff)
            if i % 50 == 49:
                session.commit()
        _seed_article_views(session, rng, days, tickets, now)
        session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickets", type=int, default=300)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--reset", action="store_true", help="Delete all demo data and exit.")
    parser.add_argument("--if-empty", action="store_true", help="Do nothing if demo data already exists.")
    args = parser.parse_args()
    init_db()
    if args.if_empty:
        with Session(engine) as session:
            if session.exec(select(Ticket.id).where(Ticket.demo == True)).first():  # noqa: E712
                print("Demo data already present; skipping.")
                return
    with Session(engine) as session:
        removed = reset_demo(session)
    if args.reset:
        print(f"Removed {removed} demo tickets.")
        return
    seed(args.tickets, args.days)
    with Session(engine) as session:
        n = len(session.exec(select(Ticket.id).where(Ticket.demo == True)).all())  # noqa: E712
    print(f"Seeded {n} demo tickets over the last {args.days} days.")


if __name__ == "__main__":
    main()
