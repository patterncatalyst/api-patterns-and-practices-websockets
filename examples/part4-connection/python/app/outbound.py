"""Ch12 example — server-side backpressure on the outbound push feed.

Mirrors Part 3 Ch10's CLIENT-side bounded buffer
(`../../part3-handling-events/clients`), but on the SERVER's outbound path:
a bounded `asyncio.Queue` decouples the producer (the fixture replay here;
"a new handling event was just recorded" in a real backend) from the actual
`websocket.send()` call, so a slow or stalled client cannot make the
producer block forever or make the server's memory grow without bound.

Two independent signals count as "the consumer fell behind":

1. The queue fills up — the producer is enqueueing faster than `drain()`
   can send, i.e. a sustained rate mismatch.
2. A single `send()` call itself hangs past `SEND_TIMEOUT_S` — the client's
   TCP receive window is full because it stopped reading, so even one frame
   at a time can't get out.

Either one triggers `OUTBOUND_BACKPRESSURE_POLICY`:

  close (default) — raise `SlowConsumerError`; the caller
                    (`app/ws_server.py`) closes the connection with
                    `CLOSE_CODE_SLOW_CONSUMER` (4290). This is the safer
                    default: an unbounded number of slow clients each
                    holding a full queue is a resource-exhaustion path.
  drop            — log a warning and discard the frame that triggered the
                    overrun, keeping the connection open. Appropriate for a
                    feed where a dropped update is superseded by the next
                    one anyway (a ticker, a live position) and closing on
                    every transient stall would be worse than a gap. NOT a
                    good fit for this channel's actual semantics — a missed
                    HandlingEvent is a correctness problem, not a
                    supersede-by-the-next-one one — so `close` is the
                    default; `drop` exists to show the trade-off, see
                    README.md.
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("handling-events-python")

QUEUE_MAXSIZE = int(os.environ.get("OUTBOUND_QUEUE_MAXSIZE", "32"))
SEND_TIMEOUT_S = float(os.environ.get("OUTBOUND_SEND_TIMEOUT_S", "5.0"))
BACKPRESSURE_POLICY = os.environ.get("OUTBOUND_BACKPRESSURE_POLICY", "close").strip().lower()

# 4290: slow-consumer / backpressure close (Part 4 convention, shared with
# the Quarkus sibling). In the 4000-4999 private-use range so it can't be
# confused with an RFC 6455 standard code.
CLOSE_CODE_SLOW_CONSUMER = 4290


class SlowConsumerError(Exception):
    """Raised by `OutboundQueue` when `BACKPRESSURE_POLICY == "close"` and a
    sustained overrun is detected. The caller is expected to close the
    WebSocket connection with `CLOSE_CODE_SLOW_CONSUMER`.
    """


class OutboundQueue:
    """Bounded queue decoupling frame production from the actual socket
    write. `enqueue()` is synchronous and non-blocking, so a fast producer
    never waits on a slow network peer directly. `drain(websocket)` is the
    long-running coroutine that performs the actual `send()` calls, in
    order, one at a time.
    """

    def __init__(self, maxsize: int = QUEUE_MAXSIZE, policy: str = BACKPRESSURE_POLICY) -> None:
        if policy not in ("close", "drop"):
            raise ValueError(f"unknown OUTBOUND_BACKPRESSURE_POLICY: {policy!r}")
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._policy = policy

    def enqueue(self, frame: str) -> None:
        """Enqueue one outbound frame (a JSON string). On a full queue,
        applies the configured policy immediately rather than blocking the
        producer — see module docstring.
        """
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            self._on_backpressure(f"outbound queue full (maxsize={self._queue.maxsize})")

    async def drain(self, websocket) -> None:
        """Pop frames and send them, one at a time, in enqueue order. A
        single send that doesn't complete within `SEND_TIMEOUT_S` is treated
        as the same "slow consumer" condition as a full queue.
        """
        while True:
            frame = await self._queue.get()
            try:
                await asyncio.wait_for(websocket.send(frame), timeout=SEND_TIMEOUT_S)
            except asyncio.TimeoutError:
                self._on_backpressure(
                    f"send() exceeded {SEND_TIMEOUT_S}s — peer is not draining its receive buffer"
                )

    def _on_backpressure(self, detail: str) -> None:
        if self._policy == "close":
            logger.warning("slow consumer detected (%s) — closing with %d", detail, CLOSE_CODE_SLOW_CONSUMER)
            raise SlowConsumerError(detail)
        logger.warning("slow consumer detected (%s) — dropping frame (policy=drop)", detail)
