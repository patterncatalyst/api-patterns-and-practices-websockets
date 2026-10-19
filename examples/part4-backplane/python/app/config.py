"""Part 4 example — env-derived configuration, centralized so every module
reads settings the same way (mirrors the pattern in
`examples/part4-connection/python/app/auth.py`'s module-level constants).
"""
from __future__ import annotations

import os

# Ch18 instance identity (PROTOCOL.md "Instance identity") — logged on every
# connection accept and every event delivery so verify.sh can prove an
# injected event crossed from instance B to a client connected to instance A.
INSTANCE_ID = os.environ.get("INSTANCE_ID", "python-a")

# Ch18 backplane mode (PROTOCOL.md "Backplane modes") — stateless|kafka|redis.
BACKPLANE_MODE = os.environ.get("BACKPLANE_MODE", "stateless")

# WS/HTTP listener ports — 8081/8082 match the Part 3/Part 4-connection
# Python examples; 8080 stays reserved for the Quarkus sibling. A second
# instance (python-b) overrides these (8084/8085 — see PROTOCOL.md "Ports").
WS_HOST = os.environ.get("WS_HOST", "0.0.0.0")
WS_PORT = int(os.environ.get("WS_PORT", "8081"))
HTTP_HOST = os.environ.get("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8082"))

WS_PING_INTERVAL_S = float(os.environ.get("WS_PING_INTERVAL_S", "20"))
WS_PING_TIMEOUT_S = float(os.environ.get("WS_PING_TIMEOUT_S", "20"))

# Kafka backplane (BACKPLANE_MODE=kafka).
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "handling-events")

# Redis backplane (BACKPLANE_MODE=redis).
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
