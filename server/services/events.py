"""Tiny in-process pub/sub that feeds the SSE endpoints.

AI runs execute in worker threads, so `publish()` is thread-safe: it hops onto
the event loop with call_soon_threadsafe. Single-process only; swap for Redis
pub/sub to scale out to several API workers.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

CONSOLE = "console"


def ticket_channel(ticket_id: int) -> str:
    return f"ticket:{ticket_id}"


class Broker:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subs[channel].add(q)
        try:
            yield q
        finally:
            self._subs[channel].discard(q)

    def _fanout(self, channel: str, payload: dict) -> None:
        for q in list(self._subs.get(channel, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow client; it will resync by refetching

    def publish(self, channel: str, payload: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._fanout(channel, payload)
        else:
            loop.call_soon_threadsafe(self._fanout, channel, payload)


broker = Broker()


def notify_ticket(ticket_id: int, type_: str, **data) -> None:
    """Tell the ticket's viewers and the console queue that something changed."""
    payload = {"type": type_, "ticket_id": ticket_id, **data}
    broker.publish(ticket_channel(ticket_id), payload)
    broker.publish(CONSOLE, payload)


def sse_format(payload: dict) -> str:
    return f"event: {payload.get('type', 'message')}\ndata: {json.dumps(payload, default=str)}\n\n"


# Streams end after this long and the browser's EventSource reconnects (and
# resyncs). Without a cap, open streams would block graceful server shutdown.
SSE_MAX_SECONDS = 90


def sse_response(request, channel: str):
    """Server-Sent Events stream for one channel, with keep-alive pings."""
    from starlette.responses import StreamingResponse

    async def gen():
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SSE_MAX_SECONDS
        async with broker.subscribe(channel) as q:
            yield "retry: 1500\n: connected\n\n"
            while loop.time() < deadline and not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield sse_format(payload)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
