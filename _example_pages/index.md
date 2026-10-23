---
title: "Examples"
layout: plan
permalink: /examples/
description: "Every runnable example in this repo, mapped to the chapter it supports."
---

Every hands-on chapter in this site has a matching runnable example under
[`examples/`](https://github.com/{{ site.github_username }}/{{ site.github_repo }}/tree/main/examples)
in the repo. Each example ships **both** a Quarkus (WebSockets Next) and a
Python (native `websockets`/FastAPI) implementation against the same
AsyncAPI contract, driven by a `verify.sh` that proves the two stacks
behave the same way.

| Example | What it shows | Stacks | Chapters |
|---|---|---|---|
| [part3-handling-events](https://github.com/{{ site.github_username }}/{{ site.github_repo }}/tree/main/examples/part3-handling-events) | Reference both-stack implementation of `receiveHandlingEvent`: one WebSocket connection per booking, server-to-client push only, replaying a deterministic fixture | Both | [Ch8]({{ '/docs/08-quarkus-websockets-next/' | relative_url }}), [Ch9]({{ '/docs/09-python-native-websockets/' | relative_url }}), [Ch10]({{ '/docs/10-clients-reconnect-backpressure/' | relative_url }}), [Ch11]({{ '/docs/11-polyglot-one-contract-two-stacks/' | relative_url }}) |
| [part4-connection](https://github.com/{{ site.github_username }}/{{ site.github_repo }}/tree/main/examples/part4-connection) | The four connection concerns on top of part3: auth rejection, in-band error taxonomy, backpressure close, and heartbeat-detected dead peers | Both | [Ch12]({{ '/docs/12-backpressure-and-flow-control/' | relative_url }}), [Ch13]({{ '/docs/13-error-handling/' | relative_url }}), [Ch14]({{ '/docs/14-liveness-heartbeats/' | relative_url }}), [Ch17]({{ '/docs/17-security/' | relative_url }}) |
| [part4-backplane](https://github.com/{{ site.github_username }}/{{ site.github_repo }}/tree/main/examples/part4-backplane) | Scale-out fan-out across four app instances over a shared backplane, run once on Kafka and once on Redis | Both | [Ch15]({{ '/docs/15-reconnect-stateless/' | relative_url }}), [Ch16]({{ '/docs/16-reconnect-kafka-backed/' | relative_url }}), [Ch18]({{ '/docs/18-scale-out-and-fanout/' | relative_url }}) |
| [part5-performance](https://github.com/{{ site.github_username }}/{{ site.github_repo }}/tree/main/examples/part5-performance) | The same fixture replay in two wire encodings, JSON and Protobuf, negotiated via `Sec-WebSocket-Protocol` | Both | [Ch19]({{ '/docs/19-binary-protobuf-over-websockets/' | relative_url }}), [Ch20]({{ '/docs/20-optimizing-throughput/' | relative_url }}) |
| [part6-observability](https://github.com/{{ site.github_username }}/{{ site.github_repo }}/tree/main/examples/part6-observability) | The same channel with live OpenTelemetry tracing, structured logs, and metrics exported across the WS-to-LGTM seam | Both | [Ch23]({{ '/docs/23-observability/' | relative_url }}) |
| [part6-testing](https://github.com/{{ site.github_username }}/{{ site.github_repo }}/tree/main/examples/part6-testing) | The functional-HTTP and load testing layer at this site's HTTP seams: Newman for functional checks, k6 for load, against part4-backplane's compose stack | Both | [Ch21]({{ '/docs/21-testing-websockets/' | relative_url }}) |

## Running an example

Each directory is self-contained: a `README.md` (or `PROTOCOL.md` for the
wire-level contract), a `compose.yaml`, and a `verify.sh` that proves it
against the shared `contracts/asyncapi.yaml`.

```bash
cd examples/part3-handling-events && ./verify.sh
```

See [Setup and the Lab]({{ '/docs/00-setup-and-the-lab/' | relative_url }}) for the full toolchain setup.
