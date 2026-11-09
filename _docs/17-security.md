---
title: "Security"
order: 17
part: "Production Concerns"
description: "Authenticating a long-lived connection at the upgrade with a bearer JWT, and the attack surface specific to WebSockets."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why a browser's `WebSocket` constructor can't attach an `Authorization` header, and where a bearer token goes instead.
- Validate an HS256 JWT at the upgrade on both stacks: structure, constant-time signature comparison, then `exp`, before a single frame is sent.
- Collapse every validation failure into one `1008` close with no detail on the wire, and say what that defeats.
- Choose between rejecting in a pre-handshake hook and validating right after accept.
- State what a move to OIDC with RS256 and a JWKS endpoint changes, and why it removes the secret-rotation problem.

## Why this matters

Backpressure, the error envelope and heartbeats all run against a socket that is already open, and none of them ask who opened it. The check has to live at the upgrade, and the upgrade is an HTTP `GET` that a browser can't put an `Authorization` header on. The token travels somewhere else, and the stack must reject a bad one before the first frame leaves. A valid JWT gets the feed. Everything else gets a `1008` close and nothing more.

## Why a WebSocket can't just send an Authorization header

The browser `WebSocket` constructor takes a URL and an optional list of subprotocol strings. It has no way to set request headers on the opening handshake. A server-side client, `websocat` or the Python `websockets` `connect()` can set any header it likes, but the contract serves both kinds of client on one channel, so the token has to travel where the browser API allows: the URL, or the subprotocol list.

| Carrier | Reads as | Exposure |
|---|---|---|
| `?token=<jwt>` query parameter | The contract's `token` parameter, parsed by `parse_qs` in Python and by hand from `handshakeRequest().query()` on Quarkus, which does not split query parameters for you | Lands in access logs, CDN logs, browser history and proxy traces, none of which treat a query string as sensitive |
| `Sec-WebSocket-Protocol` entry such as `Bearer.<jwt>` | A second job for the list that already carries the `handling-events.v1` version tag | Stays out of the URL and browser history, but any log that captures request headers captures it |

This channel uses the query parameter, which the contract marks `required`. Neither server inspects the subprotocol list beyond its version tag, and requiring a credential there would reject plain clients (`websocat`, browsers without the subprotocol wired up) that don't offer one. The mitigation for the logging exposure is a short token lifetime plus TLS in transit. If the logging exposure is unacceptable, exchange a short-lived, single-use upgrade token for a session credential after the connection opens.

## Validating at the upgrade

Both stacks run the same three checks in the same order: structure, signature, expiry.

Python hands the work to PyJWT, pinning `algorithms` to `["HS256"]`. A decoder that trusts the `alg` field inside the token opens the door to `alg: none` and algorithm-confusion attacks, where a token signed with nothing, or with a key the verifier never expected, still passes. Quarkus does the work by hand, because the HS256 shared secret doesn't justify `quarkus-smallrye-jwt`, which is built for RS256 and JWKS. It splits the token on `.`, requires three segments, recomputes the HMAC over `header.payload` and compares with `MessageDigest.isEqual`. A short-circuiting `Arrays.equals` leaks how many leading bytes matched through how long the comparison took, which lets an attacker recover a signature one byte at a time. `isEqual` takes the same time wherever the first mismatch falls. Only after the signature passes does `verify` read `exp`.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    public static VerificationResult verify(String token, String secret) {
        if (token == null || token.isBlank()) {
            return VerificationResult.rejected("missing token");
        }
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            return VerificationResult.rejected("malformed token (expected 3 segments, got " + parts.length + ")");
        }
        try {
            String signingInput = parts[0] + "." + parts[1];
            byte[] expectedSignature = hmac(signingInput, secret);
            byte[] actualSignature = URL_DECODER.decode(parts[2]);
            if (!MessageDigest.isEqual(expectedSignature, actualSignature)) {
                return VerificationResult.rejected("bad signature");
            }

            Map<?, ?> claims = MAPPER.readValue(URL_DECODER.decode(parts[1]), Map.class);
            Object expClaim = claims.get("exp");
            if (!(expClaim instanceof Number expNumber)) {
                return VerificationResult.rejected("missing or invalid exp claim");
            }
            if (Instant.now().getEpochSecond() >= expNumber.longValue()) {
                return VerificationResult.rejected("expired");
            }

            Object sub = claims.get("sub");
            return VerificationResult.ok(sub == null ? null : sub.toString());
        } catch (Exception e) {
            return VerificationResult.rejected("malformed token: " + e.getMessage());
        }
    }
```
```python
def validate_token(token: str | None) -> dict:
    """Validate a bearer token and return its decoded claims, or raise
    `AuthError`. Checks (in PyJWT's own order): signature, then `exp`
    (expiry); PyJWT's `decode` performs both before returning.
    """
    if not token:
        raise AuthError("missing token")
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("expired token") from exc
    except jwt.InvalidSignatureError as exc:
        raise AuthError("bad signature") from exc
    except jwt.InvalidTokenError as exc:
        # Catch-all for every other PyJWT decode failure (malformed token,
        # wrong algorithm, not-yet-valid `nbf`, missing required claims if
        # configured, ...). InvalidTokenError is PyJWT's common base class
        # for all of these.
        raise AuthError(f"invalid token: {exc}") from exc
```

Tokens carry `sub`, `bookingId`, `iat` and `exp`. Both stacks ship a minter with three modes, so one script can mint tokens that work against either server.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    public static String mintValid(String bookingId, String secret) {
        Instant now = Instant.now();
        return JwtHs256.mint(DEFAULT_SUBJECT, bookingId, now, now.plus(Duration.ofMinutes(15)), secret);
    }

    public static String mintExpired(String bookingId, String secret) {
        Instant now = Instant.now();
        return JwtHs256.mint(DEFAULT_SUBJECT, bookingId, now.minus(Duration.ofMinutes(30)),
                now.minus(Duration.ofMinutes(15)), secret);
    }

    public static String mintBadSignature(String bookingId, String secret) {
        // Signed with a DIFFERENT secret than the server validates against,
        // so JwtHs256.verify() against the real secret fails on signature
        // comparison, not on structure or expiry.
        return mintValid(bookingId, secret + "-wrong");
    }
```
```python
def mint(mode: str, booking_id: str, ttl_seconds: int) -> str:
    now = int(time.time())
    claims = {
        "sub": "test-client",
        "bookingId": booking_id,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    secret = JWT_SECRET

    if mode == "expired":
        claims["iat"] = now - ttl_seconds - 10
        claims["exp"] = now - 10
    elif mode == "bad-sig":
        secret = JWT_SECRET + "-wrong"
    elif mode != "valid":
        raise ValueError(f"unknown mode: {mode!r}")

    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)
```

## Where to reject: process_request or after accept

The `websockets` library's `process_request` hook runs before the `101 Switching Protocols` response, and its only return value is an HTTP response. No WebSocket exists yet, so there is no close code to send. Rejecting there means a `401` or `403`, which would make auth the one HTTP-shaped failure beside the channel's WebSocket-shaped `4290`, `4400` and `4408`.

The Python handler instead completes the handshake, validates the token first, and closes with `1008` before `_run_connection` streams anything. Quarkus has no choice to make: `@OnOpen` already runs after the handshake, so `onOpen` validates and closes with `CloseCodes.AUTH_FAILURE` as its first action.

The outcome is nearly the same to a client: no data arrives and the socket closes. On the wire it differs. A `101` followed by a close frame is not a `401` that never upgrades, and a proxy that logs or retries those cases differently can tell them apart. Check whether a third WebSocket library offers a pre-handshake hook that can send a close code, or only an HTTP-response hook like `process_request`.

{% include excalidraw.html file="17-auth-upgrade-flow" alt="A client sends a GET with a token query parameter. A dashed box marks where Python's process_request hook would run, before the handshake completes, where only an HTTP response is possible. The solid path goes through the 101 response to a validation step in the handler. A valid, unexpired token reaches the accept box that streams the feed. A missing, malformed, expired or badly signed token reaches a reject box that closes 1008 with no data and no reason." caption="Figure 17.1: Both stacks accept the handshake, then validate the token first and close 1008 before any frame goes out. Python's process_request hook runs too early to send that close code." %}

## One code for every failure

A missing, malformed, badly signed or expired token all close with `1008`, no data and no message saying which check failed. An oracle that answers "bad signature" differently from "expired" gives a prober two facts: whether it holds a working key, and whether a fresher `exp` is worth forging. One generic close denies both. The specific reason is logged server side (`logger.warning` in Python, `Log.warnf` in Quarkus), so an operator debugging a client still sees it. It never crosses the wire.

## Token lifetime and secret rotation

The token is checked once, at the upgrade. A token that expires a second after the connection opens has done its job, and the socket keeps streaming. Minted tokens live five minutes in Python and fifteen on Quarkus. For a feed that stays open for hours, close the connection when the token's `exp` lapses and make the client reconnect with a fresh token, or add a mid-connection re-auth frame. A reconnecting client needs a fresh token for every attempt, so its backoff loop has to fetch one.

Rotating the shared secret has no graceful path. Every verifier must learn the new secret at the same moment, or tokens fail wherever the other value still loads. A rolling deploy needs a verifier that accepts both secrets for an overlap window, and neither stack's check does.

## Where production differs: OIDC, RS256 and JWKS

The self-minted HS256 token is a deliberate scope boundary: a real OIDC provider in CI adds cold-start time and JWKS-endpoint flakiness for no teaching gain. An identity provider such as Keycloak removes the shared secret. It signs tokens with a private key only it holds, usually RS256 or ES256, and publishes the public keys at a JWKS endpoint (`/realms/<realm>/protocol/openid-connect/certs`). The resource server fetches and caches them, and can verify a signature but never forge one. The provider rotates its key by publishing the new public key beside the old one for an overlap window, and verifiers pick it up when their cache refreshes. No coordinated redeploy.

Verification changes shape: look up the public key for the token's `kid`, then verify against it. That is why `quarkus-oidc`, or an equivalent client on Python, is worth the dependency here. Pinning the expected algorithm matters more, not less: a careless verifier that trusts the token's own `alg` header can be handed a token it should never accept.

{% include excalidraw.html file="17-hs256-vs-keycloak" alt="Two columns showing the same bearer JWT at the upgrade with different trust models. The left column, the self-minted HS256 setup, has one process minting and a single symmetric secret shared by every minter and verifier, checked by recomputing the HMAC. The right column, the production path, has an OIDC provider issuing RS256 tokens and publishing public keys at a JWKS endpoint, checked against the rotating public key with no shared secret." caption="Figure 17.2: A self-minted HS256 shared secret and the OIDC path with RS256 and JWKS both put a bearer JWT at the upgrade. Only the trust model behind the signature differs." %}

## TLS is not optional

Everything here runs on plain `ws://` because a local Compose project has no certificate to present. Over a real network that sends `?token=<jwt>` in the clear. `wss://` encrypts the whole upgrade request, query string included, and is what makes the token-in-the-URL trade-off tolerable. The server that terminates TLS still logs the plaintext URL. Without TLS, anyone on the path can read the token.

> **Decision**
>
> Validate a bearer token at the upgrade, as the first thing the connection handler does. Carry it as a query parameter (or a `Sec-WebSocket-Protocol` entry), keep its lifetime short, and always use `wss://`. Close every failure with one code and log the reason server side. If the library has a pre-handshake hook that can send a WebSocket close code, use it. If it only has an HTTP-response hook, validate right after accept and close `1008` before sending data. Treat a self-minted HS256 shared secret as a teaching device. In production use an OIDC provider with RS256 or ES256 and a JWKS endpoint, so no two services have to hold the same secret.

> **🤖 Explore with your agent**
>
> "In examples/part4-connection, the handling-events channel closes any bad token with 1008 and ignores the token after the upgrade. Add a close at the token's exp claim on both stacks: the Python handler in python/app/ws_server.py and HandlingEventConnectionWebSocket on Quarkus. Use close code 1008 and the same 'authentication failed' reason, and keep the failure reason out of the frame."
>
> Check: mint a token with `uv run python -m app.mint_token --ttl 5`, connect to port 8081 and 8080, and confirm the socket closes with 1008 about five seconds after it opens, then run `./verify.sh`.

## Build, run, observe

```bash
cd examples/part4-connection
./verify.sh
```

`verify.sh` starts both stacks (Quarkus on `:8080`, Python on `:8081`) under Docker Compose, mints one set of tokens, and checks each stack. A valid token gets the first fixture frame, `RECEIVE` for the fixture booking. Missing, garbage, expired and wrong-secret tokens each get no frame. The script prints `ok, ` per check and `PASS: ` when both stacks agree. `websocat` can't read the close code, so a rejection counts as no `101` or an immediate close after one.

Mint a token by hand. The default secret is 20 bytes, so PyJWT prints `InsecureKeyLengthWarning`, because RFC 7518 recommends at least 32 bytes for HS256. Set `WS_JWT_SECRET` to something longer for anything beyond local use.

```bash
cd examples/part4-connection/python
uv run python -m app.mint_token
uv run python -m app.mint_token --mode expired
uv run python -m app.mint_token --mode bad-sig
```

- Mint an `expired` or `bad-sig` token and connect with `?token=...`: the socket closes with no frame.
- Omit `?token=` entirely: same result, with no detail in the reply.
- Set a different `WS_JWT_SECRET` on one stack: tokens minted against the other stack stop working there.

## For deeper coverage

- Gough, J., Bryant, D. & Auburn, M., *Mastering API Architecture* (O'Reilly, 2022): authentication and authorization at an API's edge, including bearer-token and token-expiry trade-offs.
- Sam Newman, *Building Microservices, 2nd Edition* (O'Reilly, 2021): the shared-secret versus identity-provider trade-off.
- *Cloud Native Design Patterns*, "Security" chapter: the four-layer (cloud, cluster, container, code) security model that upgrade-time checks belong to.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455): the `Origin` header and `Sec-WebSocket-Protocol` list, the two places a browser WebSocket can carry anything like a credential.
- [RFC 7519](https://www.rfc-editor.org/rfc/rfc7519) (JSON Web Token) and [RFC 6750](https://www.rfc-editor.org/rfc/rfc6750) (OAuth 2.0 Bearer Token Usage): the claim structure and bearer convention both stacks implement.
