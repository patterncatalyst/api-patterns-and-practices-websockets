"""Part 6 example — test-only OTel SDK wiring.

`uv run pytest` runs this app's modules WITHOUT the `opentelemetry-instrument`
wrapper (see ../Containerfile and app/main.py's docstring), so
`app.ws_server`'s module-level `trace.get_tracer(...)` call resolves against
whatever global `TracerProvider` is active at the moment a span actually
starts — the OTel Python API's tracer handle is a lazy proxy for exactly
this reason (`opentelemetry.trace.get_tracer` returns a `ProxyTracer` that
delegates to the real provider once one is set, even if `get_tracer` itself
was called earlier). Without this fixture, `tracer.start_as_current_span(...)`
in test_contract.py would use the API's built-in no-op tracer and every span
would carry the all-zero invalid trace id — technically still 32 hex
characters (passing a naive regex), but not exercising real trace-id
generation. Installing a real (exporter-less) SDK `TracerProvider` here, once
per test session, makes the span under test behave the same way it does in
production under `opentelemetry-instrument` — same trace-id generation, just
no OTLP export.
"""
from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider


@pytest.fixture(scope="session", autouse=True)
def _otel_sdk_tracer_provider() -> None:
    trace.set_tracer_provider(TracerProvider())
