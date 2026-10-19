"""Part 4 example — the backplane abstraction (Ch18 fan-out, DRQ-005).

Three interchangeable implementations of `Backplane` (see `base.py`),
selected at process startup by `BACKPLANE_MODE` (see `app/config.py`):

  - `stateless` (default) — `stateless_backplane.StatelessBackplane`:
    in-process only, no cross-instance fan-out.
  - `kafka` — `kafka_backplane.KafkaBackplane`: shared Kafka topic, durable +
    replayable (also powers Ch16's `afterEventId` resume).
  - `redis` — `redis_backplane.RedisBackplane`: shared Redis Pub/Sub
    channel, live fan-out only, no replay.

See `examples/part4-backplane/PROTOCOL.md` for the full behavior contract
this module implements.
"""
from __future__ import annotations

from app import config
from app.backplane.base import Backplane
from app.backplane.kafka_backplane import KafkaBackplane
from app.backplane.redis_backplane import RedisBackplane
from app.backplane.stateless_backplane import StatelessBackplane

__all__ = ["Backplane", "create_backplane"]


def create_backplane(mode: str | None = None) -> Backplane:
    """Instantiate the `Backplane` implementation for `mode` (default:
    `config.BACKPLANE_MODE`, i.e. the `BACKPLANE_MODE` env var). Does not
    call `start()` — the caller (see `app/main.py`) owns that, since it's
    async and needs to run on the event loop.
    """
    resolved = (mode or config.BACKPLANE_MODE).strip().lower()
    if resolved == "stateless":
        return StatelessBackplane()
    if resolved == "kafka":
        return KafkaBackplane(config.KAFKA_BOOTSTRAP_SERVERS, config.KAFKA_TOPIC)
    if resolved == "redis":
        return RedisBackplane(config.REDIS_URL)
    raise ValueError(f"unknown BACKPLANE_MODE={resolved!r} (expected stateless|kafka|redis)")
