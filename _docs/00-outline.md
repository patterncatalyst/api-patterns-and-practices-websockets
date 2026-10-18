---
title: "Outline"
order: 0
overview: true
part: "Prerequisites"
description: "What this site covers and how it's organized — 29 chapters across 9 parts, both stacks against one AsyncAPI 3 contract."
---

This site teaches WebSocket API design against a single AsyncAPI 3 contract for a
shipping and cargo domain. The socket here pushes a live **handling-event feed** —
container moves, customs holds, delivery confirmations — to any client watching a
booking, instead of making that client poll the sibling REST booking service for a
status that hasn't changed. Every hands-on chapter ships the same example in **both
Quarkus WebSockets Next and Python** (FastAPI/Starlette plus the native `websockets`
library), generated against the same contract. The full arc is below.

## Part 0 — Prerequisites
- [Ch0 · Setup and the lab](../00-setup-and-the-lab/)

## Part 1 — Foundations
- [Ch1 · The real-time problem](../01-the-real-time-problem/)
- [Ch2 · Choosing the right tool](../02-choosing-the-right-tool/)
- [Ch3 · How WebSockets work](../03-how-websockets-work/)
- [Ch4 · The shared domain](../04-the-shared-domain/)

## Part 2 — Contract-first for Sockets
- [Ch5 · AsyncAPI: giving a socket a contract](../05-asyncapi-giving-a-socket-a-contract/)
- [Ch6 · Message design](../06-message-design/)
- [Ch7 · Versioning and evolution](../07-versioning-and-evolution/)

## Part 3 — Building It
- [Ch8 · Quarkus WebSockets Next](../08-quarkus-websockets-next/)
- [Ch9 · Python native WebSockets](../09-python-native-websockets/)
- [Ch10 · Clients: reconnect and backpressure](../10-clients-reconnect-backpressure/)
- [Ch11 · Polyglot: one contract, two stacks](../11-polyglot-one-contract-two-stacks/)

## Part 4 — Production Concerns
- [Ch12 · Backpressure and flow control](../12-backpressure-and-flow-control/)
- [Ch13 · Error handling](../13-error-handling/)
- [Ch14 · Liveness and heartbeats](../14-liveness-heartbeats/)
- [Ch15 · Reconnect: stateless](../15-reconnect-stateless/)
- [Ch16 · Reconnect: Kafka-backed](../16-reconnect-kafka-backed/)
- [Ch17 · Security](../17-security/)
- [Ch18 · Scale-out and fan-out](../18-scale-out-and-fanout/)

## Part 5 — Performance & Optimization
- [Ch19 · Binary Protobuf over WebSockets](../19-binary-protobuf-over-websockets/)
- [Ch20 · Optimizing throughput](../20-optimizing-throughput/)

## Part 6 — Testing, Debugging & Observability
- [Ch21 · Testing WebSockets](../21-testing-websockets/)
- [Ch22 · Debugging WebSockets](../22-debugging-websockets/)
- [Ch23 · Observability](../23-observability/)
- [Ch24 · Anti-patterns](../24-anti-patterns/)

## Part 7 — Runtime Progression
- [Ch25 · Docker Compose](../25-docker-compose/)
- [Ch26 · Kubernetes (minikube)](../26-kubernetes-minikube/)
- [Appendix A · OpenShift Local (CRC)](../99-appendix-a-openshift-crc/)

## Part 8 — The Bigger Picture
- [Ch27 · When you don't need a socket](../27-when-you-dont-need-a-socket/)
- [Ch28 · Final project](../28-final-project/)
