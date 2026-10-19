"""Part 6 example — Ch23 observability ANCHOR metric (DRQ-029).

`prometheus-client`'s `Counter` registers itself in the DEFAULT global
registry at import time, so both `app/ws_server.py` (which increments it per
delivered `HandlingEvent`) and `app/http_app.py`'s `/metrics` endpoint
(which scrapes the same default registry via `generate_latest()`) see the
identical counter object just by importing this module — no registry
wiring required. This mirrors the Quarkus sibling's
`handling_events_delivered_total` (Micrometer `Counter`, same name, no
labels): a reader comparing the two stacks' `/metrics` output sees the same
metric name and semantics either way.
"""
from __future__ import annotations

from prometheus_client import Counter

HANDLING_EVENTS_DELIVERED_TOTAL = Counter(
    "handling_events_delivered_total",
    "Total number of HandlingEvent frames delivered to a WebSocket client.",
)
