---
title: "Outline"
order: 0
overview: true
part: "Prerequisites"
description: "29 chapters across 9 parts, both stacks against one AsyncAPI 3 contract."
---

A shipping and cargo handling-event feed (container moves, customs holds, delivery confirmations), pushed over WebSockets to any client watching a booking instead of making that client poll the sibling REST booking service. Every hands-on chapter builds the same example in both **Quarkus WebSockets Next and Python** (FastAPI/Starlette plus the native `websockets` library) against one AsyncAPI 3 contract. The full arc is below.

## Part 0: Prerequisites
- [0. Setup and the lab](../00-setup-and-the-lab/)

## Part 1: Foundations
- [1. The real-time problem](../01-the-real-time-problem/)
- [2. Choosing the right tool](../02-choosing-the-right-tool/)
- [3. How WebSockets work](../03-how-websockets-work/)
- [4. The shared domain](../04-the-shared-domain/)

## Part 2: Contract-first for Sockets
- [5. AsyncAPI: giving a socket a contract](../05-asyncapi-giving-a-socket-a-contract/)
- [6. Message design](../06-message-design/)
- [7. Versioning and evolution](../07-versioning-and-evolution/)

## Part 3: Building It
- [8. Quarkus WebSockets Next](../08-quarkus-websockets-next/)
- [9. Python native WebSockets](../09-python-native-websockets/)
- [10. Clients: reconnect and backpressure](../10-clients-reconnect-backpressure/)
- [11. Polyglot: one contract, two stacks](../11-polyglot-one-contract-two-stacks/)

## Part 4: Production Concerns
- [12. Backpressure and flow control](../12-backpressure-and-flow-control/)
- [13. Error handling](../13-error-handling/)
- [14. Liveness and heartbeats](../14-liveness-heartbeats/)
- [15. Reconnect: stateless](../15-reconnect-stateless/)
- [16. Reconnect: Kafka-backed](../16-reconnect-kafka-backed/)
- [17. Security](../17-security/)
- [18. Scale-out and fan-out](../18-scale-out-and-fanout/)

## Part 5: Performance & Optimization
- [19. Binary Protobuf over WebSockets](../19-binary-protobuf-over-websockets/)
- [20. Optimizing throughput](../20-optimizing-throughput/)

## Part 6: Testing, Debugging & Observability
- [21. Testing WebSockets](../21-testing-websockets/)
- [22. Debugging WebSockets](../22-debugging-websockets/)
- [23. Observability](../23-observability/)
- [24. Anti-patterns](../24-anti-patterns/)

## Part 7: Runtime Progression
- [25. Docker Compose](../25-docker-compose/)
- [26. Kubernetes (minikube)](../26-kubernetes-minikube/)
- [Appendix A · OpenShift Local (CRC)](../99-appendix-a-openshift-crc/)

## Part 8: The Bigger Picture
- [27. When you don't need a socket](../27-when-you-dont-need-a-socket/)
- [28. Final project](../28-final-project/)
