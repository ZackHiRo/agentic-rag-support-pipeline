"""Ticket lifecycle automation, run periodically from the app lifespan.

- Pending (waiting on the player) for PENDING_REMINDER_DAYS → one friendly reminder.
- Pending for PENDING_AUTOSOLVE_DAYS → solved automatically ("auto").
- Solved for SOLVED_AUTOCLOSE_DAYS → closed (a player reply before that reopens it).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, select

from ..db import engine, utcnow
from ..models import AuthorKind, Ticket, TicketStatus
from ..settings import settings
from .events import notify_ticket
from .tickets import add_message, log_event, resolved_by_for, set_status

log = logging.getLogger("everdawn.lifecycle")

REMINDER = (
    "Just checking in: we're still waiting to hear back from you on this ticket. "
    "Reply here whenever you're ready. If we don't hear from you, we'll close it in a few days, "
    "and you can always open a new one."
)


def sweep(now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    remind_at = now - timedelta(days=settings.pending_reminder_days)
    solve_at = now - timedelta(days=settings.pending_autosolve_days)
    close_at = now - timedelta(days=settings.solved_autoclose_days)
    counts = {"reminded": 0, "auto_solved": 0, "closed": 0}
    touched: list[int] = []
    with Session(engine) as s:
        pending = s.exec(
            select(Ticket).where(Ticket.status == TicketStatus.pending, Ticket.pending_since != None)  # noqa: E711
        ).all()
        for t in pending:
            if t.pending_since <= solve_at:
                t.resolved_by = "auto"
                set_status(s, t, TicketStatus.solved, reason="no_reply_from_player")
                counts["auto_solved"] += 1
                touched.append(t.id)
            elif t.pending_since <= remind_at and t.reminder_sent_at is None:
                add_message(s, t, author_kind=AuthorKind.system, body=REMINDER)
                t.reminder_sent_at = now
                log_event(s, t, "reminder.sent")
                counts["reminded"] += 1
                touched.append(t.id)
        solved = s.exec(
            select(Ticket).where(Ticket.status == TicketStatus.solved, Ticket.solved_at != None)  # noqa: E711
        ).all()
        for t in solved:
            if t.solved_at <= close_at:
                t.resolved_by = t.resolved_by or resolved_by_for(s, t)
                set_status(s, t, TicketStatus.closed, reason="auto_close")
                counts["closed"] += 1
                touched.append(t.id)
        s.commit()
    for tid in touched:
        notify_ticket(tid, "ticket.updated")
    return counts


async def run_forever() -> None:
    while True:
        try:
            counts = await asyncio.to_thread(sweep)
            if any(counts.values()):
                log.info("lifecycle sweep: %s", counts)
        except Exception:
            log.exception("lifecycle sweep failed")
        await asyncio.sleep(settings.lifecycle_interval_seconds)
