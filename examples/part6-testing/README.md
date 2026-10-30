# Part 6 "Testing, Debugging & Observability": Newman functional-HTTP example

This site's contract (`contracts/asyncapi.yaml`) is WebSocket-only, but the
example apps expose a handful of plain HTTP surfaces around that contract:
liveness probes, and the `examples/part4-backplane` inject endpoint that
tests use to publish an event onto the active backplane. Test tooling for
this project splits by shape: **k6** covers sustained-connection *load*
against the WebSocket channel (`examples/part4-backplane/k6/smoke.js`,
`examples/part5-performance`), and **Newman** (Postman's CLI runner) covers
*functional* assertions against the REST-shaped HTTP seams. This directory
is that Newman example, cited in the testing chapter as the functional-HTTP
layer alongside the project's `verify.sh`/`lib.sh` WebSocket-assertion
corpus and the k6 smoke scripts.

There is no app here: `newman/collection.json` runs against
[`examples/part4-backplane`](../part4-backplane)'s existing compose stack,
the richest HTTP surface in the site (two stacks x two instances, always up
regardless of compose profile; see that example's own README).

## What the collection proves

| Request | Target | Expected | Why |
|---|---|---|---|
| `GET /healthz` | python-a (`:8082`), python-b (`:8085`) | `200`, body `{"status":"ok"}` exactly | Liveness probe shape both Python instances share (`app/http_app.py`). |
| `POST /internal/bookings/{bookingId}/handling-events`, schema-valid body | quarkus-a (`:8080`) | `202 Accepted` | PROTOCOL.md's "Inject endpoint": publishes onto the active backplane. |
| same, malformed body (bad `eventType` enum value) | quarkus-a | `400 Bad Request` | The `HandlingEvent` Java record has no bean validation; only Jackson's enum deserialization can reject a request, via RESTEasy Reactive's default unreadable-entity mapper (confirmed live). |
| same, schema-valid body | python-a (`:8082`) | `202 Accepted`, body echoes `status`/`eventId`/`bookingId` | Same endpoint, Python/FastAPI side. |
| same, malformed body (bad `bookingId` pattern + bad `eventType`) | python-a | `422 Unprocessable Content`, `detail[]` names both offending fields | Pydantic v2 (`app/models_generated.py`, generated from `contracts/asyncapi.yaml`'s `HandlingEvent` schema) validates both the id pattern and the enum at the request-body boundary. |

A collection-level pre-request script generates one `bookingId`/`cargoId`
pair for the whole run (reused by every item; part4-backplane's
`Backplane` implementations filter strictly by `bookingId`, so one run never
collides with another) and a fresh `eventId` before every request.

## Run it

```bash
cd examples/part6-testing
./verify.sh
```

This brings up `examples/part4-backplane/compose.yaml` on its default
(stateless) profile (no Kafka/Redis needed for these checks), waits for
both stacks' instance-A HTTP listener to answer, runs the collection via a
**pinned Newman** (`npx newman@6.2.3`; see `verify.sh`'s header comment for
why `npx` rather than the `docker.io/postman/newman` image: no `6.2.x` tag
exists there yet, and the house "upgrade the tool, never downgrade the pin"
policy rules out falling back to the image's `6.1.3`), asserts newman's own
exit code, and tears the stack down. A JSON run report lands in
`newman/reports/` (gitignored, regenerated every run).

To run against an already-running stack (e.g. one you brought up by hand)
without the compose lifecycle:

```bash
npx newman@6.2.3 run newman/collection.json -e newman/environment.json
```

## Not covered here

[`examples/part6-observability`](../part6-observability)'s HTTP surface
(`/healthz`, `/metrics`) is out of scope for this pass:

- Its **Quarkus** app has no dedicated health endpoint: no
  `quarkus-smallrye-health` dependency (confirmed in `quarkus/pom.xml`), and
  its own `compose.yaml` documents the same gap for its healthcheck. Only
  `GET /q/metrics` exists there (Micrometer/Prometheus).
- `handling_events_delivered_total` is a Micrometer counter registered in a
  `@PostConstruct` on the Quarkus endpoint's **per-connection** WebSockets
  Next bean; it is not registered (and so absent from `/q/metrics`) until a
  WebSocket connection opens at least once. Proving it live means driving a
  WS connection first and bringing up that example's hard-dependency LGTM
  stack (Grafana/Loki/Tempo/Mimir). The observability example's own
  `verify.sh` already covers that WS-plus-observability proof; duplicating
  it here would blur this example's scope from functional HTTP into
  functional HTTP plus WS plus observability stack, which this project
  keeps separate.

## Version pin

**Newman 6.2.3**, current stable on npm as of this survey (2026-10-19); see
`_docs/00-setup-and-the-lab.md`'s version matrix. `verify.sh` pins it with
`npx newman@6.2.3`, re-downloading
(and npm-caching) the exact version on first use rather than trusting
whatever `newman` happens to already be on `PATH`.

## CI

Not wired into `.github/workflows/` yet: a later wave adds a dedicated
`newman` CI job (mirroring the `k6-smoke` job's shape: bring up part4-backplane's
default-profile instances, run this collection, tear down, fail the job on
any assertion failure). This example runs standalone, by hand, until that
lands.
