---
title: "Security"
order: 17
part: "Production Concerns"
description: "Authenticating and authorizing a long-lived connection, and the attack surface specific to WebSockets."
duration: "22 min read"
---

Every chapter in Part 4 so far has assumed the connection in front of it belongs to someone who's allowed to be there. Chapter 12's backpressure guard, Chapter 13's error envelope, Chapter 14's heartbeat sweep — all of them run against a socket that's already open, and none of them ask who opened it. That gap is this chapter's whole subject: `examples/part4-connection`'s `handlingEvents` channel now rejects an unauthenticated upgrade before a single fixture frame leaves the server, on both stacks, with a bearer JWT validated against a shared HS256 secret. The interesting part isn't the cryptography — HMAC-SHA256 is a hash function with a key, nothing more — it's where the check has to live given what a WebSocket upgrade actually is: an HTTP `GET` request that a browser's `WebSocket` constructor cannot attach a custom `Authorization` header to, which pushes the token somewhere else entirely and creates a timing problem neither stack's auth code can fully dodge. `examples/part4-connection/python/app/auth.py` and `examples/part4-connection/quarkus/src/main/java/com/patterncatalyst/shipping/connection/JwtHs256.java` solve that problem two different ways in source but land on the identical outward behavior: a valid token gets the feed, everything else gets closed with code `1008` and nothing else.

## Why a WebSocket can't just send an Authorization header

A REST client attaches a bearer token the obvious way — set the `Authorization` header, send the request, done. A browser-originated WebSocket cannot do this, and it's worth being precise about why, because the workaround this chapter uses only makes sense once the constraint is clear. The `WebSocket` constructor in every browser's JavaScript API takes a URL and an optional list of subprotocol strings; it exposes no mechanism to set arbitrary request headers on the opening handshake. This isn't an oversight some future spec revision quietly fixes — it's deliberate, because a WebSocket URL is reachable from contexts an `XMLHttpRequest`/`fetch` call isn't normally exposed to in the same way (a `<script>`-injected connection, for instance), and letting arbitrary JavaScript attach arbitrary headers to a cross-origin upgrade request would reopen exactly the kind of credential-leakage surface CORS exists to close off. A server-side client — a backend service, a CLI tool, `websocat`, the `websockets` library's own `connect()` — faces no such restriction; `websocket.request.path` in `app/ws_server.py` could just as easily read an `Authorization` header off a non-browser client. But this contract targets both kinds of client under one channel (`contracts/asyncapi.yaml`'s `handlingEvents`), and a channel design that only works for one of them isn't a design, so the token has to travel somewhere the browser API actually allows: the request URL itself, or the one list the constructor does accept — subprotocols.

## Carrying the token: query parameter vs. Sec-WebSocket-Protocol

Two places exist to put a bearer token on a browser-originated WebSocket upgrade, and this example picks the first one by design rather than by default. `contracts/asyncapi.yaml`'s `servers.local.bindings.ws` defines a `token` query parameter, marked `required`, with a description that names the trade-off directly: "Placeholder auth token passed as a query parameter... until the site's auth chapter lands a header-based alternative." This chapter is that auth chapter, and the answer it lands on is: keep the query parameter. `examples/part4-connection/python/app/ws_server.py`'s `_split_path_and_token` pulls `token` out of `websocket.request.path`'s query string with `urllib.parse.parse_qs`; `examples/part4-connection/quarkus/.../connection/QueryParams.java` does the equivalent by hand, because — per its own Javadoc — "WebSockets Next does not parse query parameters for the caller," pointing instead at `WebSocketConnection#handshakeRequest().query()`, the raw, unsplit query string `HandlingEventConnectionWebSocket#onOpen` hands to `QueryParams.get(...)`.

The alternative is `Sec-WebSocket-Protocol`, the one list of strings the browser `WebSocket` constructor's second argument actually lets a client set on the opening handshake. A client could pass `["handling-events.v1", "Bearer.<jwt>"]` or similar, and a server could read the token back out of the subprotocol list it's required to echo one entry from in its `101` response. The contract already advertises a subprotocol — `headers.properties["Sec-WebSocket-Protocol"]` names `handling-events.v1` as a `const` in `servers.local.bindings.ws` — but neither `ws_server.py`'s `create_server` nor `HandlingEventConnectionWebSocket` enforces or inspects it for anything beyond what it already is: a protocol-version tag, not a credential channel. `create_server`'s own docstring explains why: "requiring it would reject plain clients (websocat, browsers without the subprotocol wired up) for no behavior this example implements beyond auth" — and overloading the one header-like list a browser client exposes to also carry a secret adds a second responsibility to a mechanism this channel doesn't need yet.

Both placements share the same caveat, and it's the reason "query parameter" is a trade-off this chapter names rather than a free win: a URL — path and query string together — is exactly the kind of string that ends up in a web server's access log, a CDN's request log, a browser's history, and a proxy's debug trace, none of which treat a query parameter as sensitive by default the way most of that same tooling treats a request header. `app/auth.py`'s module docstring is explicit that the token "travels as a `?token=<jwt>` query parameter on the WebSocket upgrade request," and the mitigation this example relies on is the token's own short TTL (Chapter's "Token expiry" section below) plus TLS in transit (see "wss:// is table stakes" below) — not pretending the query string is private. A `Sec-WebSocket-Protocol` entry isn't meaningfully more private end-to-end — proxies and application logs that capture request headers capture it just as readily — but it does at least stay out of the URL a browser's own history remembers and a referrer header might forward. Neither option makes a long-lived bearer token in a URL-adjacent location disappear; a production deployment that can't tolerate the logging exposure needs a short-lived, single-use upgrade token exchanged for a session credential after the connection opens, which is out of scope for this contract's one-shot bearer check.

## Validating at the upgrade: HS256, a shared secret, and what gets checked

Once the token is off the wire, both stacks run the identical sequence of checks against it, just with different libraries doing the work. `app/auth.py`'s `validate_token` wraps PyJWT's `jwt.decode(token, JWT_SECRET, algorithms=["HS256"])` — explicitly pinning `algorithms` to a single value, which matters more than it looks: a JWT decoder that trusts the `alg` field embedded in the token itself, rather than a value the caller pins, opens the door to an `alg: none` or algorithm-confusion attack where a token signed with nothing, or signed under a different key the verifier wasn't expecting, still passes. PyJWT's `decode` call does the signature check and the `exp` (expiry) check in one pass, and `validate_token` sorts the two exceptions it can raise — `jwt.ExpiredSignatureError` and `jwt.InvalidSignatureError` — into a single `AuthError`, with every other `jwt.InvalidTokenError` subclass (malformed structure, wrong algorithm, a not-yet-valid `nbf`) collapsing into the same type through a catch-all clause.

`examples/part4-connection/quarkus/.../connection/JwtHs256.java`'s `verify` method does the same work by hand, because the chapter's Javadoc is explicit about not reaching for `quarkus-smallrye-jwt`: that extension "is built around RS256/JWKS... the right shape for a multi-service-audience token, but overkill for this chapter's single shared-secret HS256 token." `verify` splits the compact token on `.`, requires exactly three segments, recomputes the HMAC over `header.payload` with `javax.crypto.Mac`, and compares it against the token's own signature segment using `MessageDigest.isEqual` rather than `Arrays.equals` — a detail worth not skating past, because a short-circuiting byte comparison leaks how many leading bytes matched through how long the comparison took, turning a signature check into a timing oracle an attacker can mine one byte at a time. `MessageDigest.isEqual` runs in time independent of where the first mismatch falls, closing that leak. Only after the signature checks out does `verify` decode the payload and compare its `exp` claim against `Instant.now()`.

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
    (expiry) -- PyJWT's `decode` performs both before returning."""
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
        # wrong algorithm, not-yet-valid nbf, missing required claims...).
        raise AuthError(f"invalid token: {exc}") from exc
```

Both sides check exactly the same three things in the same order — structure, signature, expiry — against the same secret, which is what lets `verify.sh` mint one token with one Python script and use it against either stack without either one knowing the other exists.

## The process_request-vs-handler trade-off

Here's the detail that makes this chapter's Python implementation more interesting than "call a library function": the `websockets` library's `process_request` hook — the intended place to reject a connection before the opening handshake completes — runs too early to do what this channel needs. `process_request` fires before the `101 Switching Protocols` response is sent, and its *only* return option is an HTTP response: a status code, headers, a body. At that point in the exchange, no WebSocket connection exists yet, which means there is no such thing as a WebSocket close code to hand back — `1008` (policy violation) is a concept that only exists on an open WebSocket connection, and `process_request` runs before one exists. Rejecting there would mean answering with an HTTP `401` or `403` instead, which is a perfectly normal thing for an HTTP endpoint to do, but it means this channel's auth failures would look categorically different from its other three connection-concern failures (Chapter 12's `4290`, Chapter 13's `4400`, Chapter 14's `4408`) — one HTTP-shaped, three WebSocket-close-shaped — for a caller that has to reason about all four as rejections of the same kind of thing.

`app/ws_server.py`'s `handler` function picks the other option: let the opening handshake complete normally, then validate the token as the very first thing the handler does, before `_run_connection` starts streaming anything. The comment above that call in `handler` spells out the reasoning directly:

> the `websockets` library's `process_request` hook runs before the opening handshake completes and can only return an HTTP response (no application close code exists yet, since there is no WebSocket connection yet). Closing with 1008 immediately after accepting — and before sending a single fixture frame — delivers the same "no data, unambiguous rejection" outcome... while keeping the application-level close code the auth failure deserves.

That's the trade-off: this example accepts the WebSocket handshake for every connection — authenticated or not — and then closes unauthenticated ones immediately, rather than ever sending back an HTTP-level rejection before the upgrade. The observable outcome to a client is nearly identical either way (no data arrives, the connection doesn't stay open), which is exactly what `examples/_lib/lib.sh`'s `assert_ws_rejected` helper treats interchangeably — "a non-101 response and an immediate post-upgrade close identically" — but it is not *actually* identical on the wire: a `101` response followed instantly by a close frame is a different sequence of bytes than a `401` that never upgrades at all, and a sufficiently picky intermediary (a proxy that treats "upgraded, then closed" and "never upgraded" differently for logging or retry purposes) could tell them apart even if a test harness doesn't.

Quarkus's WebSockets Next sidesteps this particular tension by construction rather than by choice: `@OnOpen` methods run *after* the handshake has already completed, so there was never an option to reject at the HTTP layer in the first place — `HandlingEventConnectionWebSocket#onOpen` validates the token and calls `connection.close(new CloseReason(CloseCodes.AUTH_FAILURE, "authentication failed"))` as its very first action, structurally identical to the Python handler's approach, just without a `process_request`-shaped alternative ever being on the table. Both stacks converge on the same outward behavior for a different reason — Python chose it after weighing an HTTP-rejection alternative that existed; Quarkus never had that alternative to weigh — which is worth knowing if you're evaluating a third WebSocket library: check whether it gives you a pre-handshake hook with access to a close code, or only an HTTP-response-only hook like `websockets`'s, before assuming you can reject "at the door" the way an HTTP middleware would.

{% include excalidraw.html file="17-auth-upgrade-flow" alt="A client box sends a GET request carrying a token query parameter to an opening-handshake box. A ghost dashed box labeled process_request hook, Python, sits to the side with a dashed arrow from the handshake box labeled would run here, annotated that it runs before the handshake completes and can only return an HTTP response since no WebSocket close code exists yet. The main flow continues downward from the handshake box to a 101 Switching Protocols box, then to a VALIDATE box in the handler running validate_token or JwtHs256 dot verify, checking HS256 signature and expiry before any fixture frame is sent. From VALIDATE an amber arrow labeled valid signature plus unexpired goes to an ACCEPT box that streams the fixture replay, and a dashed arrow labeled missing slash garbage slash expired slash bad-sig goes to a REJECT box reading close 1008, no data sent, no reason echoed. A caption states that process_request can only answer with an HTTP response with no app close code yet, so this example validates right after accept and closes 1008 instead." caption="Figure 17.1 -- both stacks accept the handshake, then validate the token as the first thing the handler does, closing 1008 before any fixture frame goes out; Python's process_request hook exists but runs too early to issue that close code." %}

## Collapsing every failure into one code: 1008, no exceptions

Four distinct ways a token can fail — absent entirely, structurally malformed, signed with the wrong key, or expired — and both stacks map every one of them to the exact same outcome: close code `1008`, no fixture data sent, no detail about which check failed echoed back to the client. `app/auth.py`'s `AuthError` class states the reasoning as a design comment, not an afterthought: "missing, malformed, badly signed, and expired tokens are all indistinguishable to an attacker probing the channel, so they all collapse to the same generic rejection rather than leaking which specific check failed." `JwtHs256.VerificationResult`'s Javadoc makes the identical argument for the Quarkus side: the `reason` field is "logged server-side only... never echoed back to the client on the wire, so a prober can't use it as a signature oracle."

The attack this collapsing defeats is a real, named category: an oracle that answers "was the signature close?" differently from "was the token merely expired?" lets an attacker iterate — try a token, learn something from the response's shape or timing, adjust, try again — against a server that's effectively grading each guess. A server that replies `invalid signature` for a tampered token but `token expired` for a stale-but-correctly-signed one has handed an attacker exactly the two bits of information needed to tell "I don't have a working key" from "I have a working key, I just need a fresher timestamp" — the second case meaning forging a new `exp` against an already-known-good signature might be worth pursuing. Collapsing both into `1008` with no message denies that signal entirely. The specific reason is still available — both `AuthError`'s message and `VerificationResult.reason()` get logged server-side (`logger.warning` in Python, `Log.warnf` in Quarkus) — so an operator debugging a client integration issue isn't flying blind; the information just never crosses the wire to the client that triggered it.

## Minting a token: the same claims shape, two implementations

Nothing in this example stands up an identity provider, which means something still has to produce tokens for `verify.sh` and for manual testing. Both stacks ship a standalone minter that signs the identical claim shape — `sub`, `bookingId`, `iat`, `exp` — against the same `WS_JWT_SECRET`, with three named modes covering the three failure shapes the verify step exercises.

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
    // Signed with a DIFFERENT secret than the server validates against.
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

`TokenMinter`'s Javadoc notes it "mirrors the Python sibling's `app/mint_token.py` one-for-one (same default booking id, same three modes)," and that symmetry is what lets `verify.sh` mint every token it needs with a single `uv run --with pyjwt` call and use the result against both stacks interchangeably — a token minted for the Python test harness is just as valid against the Quarkus server, because both verify the same claims against the same secret the same way.

## Token expiry: the TTL is the only rotation this example has

Every minted token in this chapter carries a fifteen-minute (Quarkus) or five-minute (Python's default, `DEFAULT_TTL_SECONDS = 300`) `exp` claim, and that's the entirety of this example's lifecycle management. There is no refresh-token flow, no re-authentication mid-connection, no mechanism for a client to extend a session without reconnecting. This is a deliberate scope boundary rather than an oversight worth apologizing for: the token is checked exactly once, at the upgrade, and once a connection is open neither `JwtHs256.verify` nor `validate_token` runs again for the lifetime of that socket — a token that expires one second after the connection opens has already done its one job and the connection keeps streaming regardless, because nothing in `_run_connection` or `OutboundBackpressureGuard.sendAll` re-checks it. For a channel that replays a fixed, three-event fixture and then idles, that's a reasonable trade-off. It stops being one for a feed that stays open for hours against a token whose `exp` has long since passed: a production deployment of this pattern needs either a hard connection-lifetime cap tied to the token's `exp` (close and force a reconnect with a fresh token when it lapses) or a mid-connection re-auth frame the client sends proactively — neither of which this teaching example implements, because neither was needed to demonstrate the upgrade-time check this chapter is actually about.

"Rotation" in the secret-management sense — replacing `WS_JWT_SECRET` itself without an outage — is a harder problem this example doesn't solve either, and a shared-secret design is exactly why: every verifier (both stacks, in this case, since `compose.yaml` sets `WS_JWT_SECRET` identically on both) has to learn the new secret at the same moment, or tokens minted against the new value fail everywhere the old value still loads, and tokens minted against the old value fail everywhere the new value has already landed. A rolling deploy — new Quarkus pods come up with the new secret while old ones still run the previous value — has no graceful window under this scheme unless the verifier accepts *both* the old and new secret for some overlap period, which neither `JwtHs256.verify` nor `validate_token` is written to do. That's one of several reasons the next section's production answer looks nothing like "generate a new random string and redeploy."

## Where production differs: Keycloak, OIDC, and RS256/JWKS

Everything in this chapter so far rests on one shared secret that every minter and every verifier has to already know — and that's precisely the property a production identity provider is built to eliminate. `_plans/decisions.md`'s DRQ-021 states the scope boundary this chapter operates under directly: "the socket authenticates with a self-minted HS256 JWT... Keycloak/OIDC is named as the production, Red Hat-aligned path but not stood up in CI" — a deliberate choice, not a gap, because a real OIDC provider brings cold-start time and JWKS-endpoint flakiness that would make this chapter's `verify.sh` slower and less deterministic for no teaching benefit over the self-minted token it uses instead.

The production shape differs from this chapter's in one structural way that matters more than any individual setting: an asymmetric keypair replaces the shared secret. Keycloak (or any OIDC-compliant provider) signs tokens with a *private* key only the identity provider ever holds, typically under RS256 or ES256, and publishes the corresponding *public* key at a well-known JWKS (JSON Web Key Set) endpoint — conventionally something like `/realms/<realm>/protocol/openid-connect/certs`. A resource server — this chapter's WebSocket endpoint, in a production version of it — fetches that public key, caches it, and verifies incoming tokens against it. The resource server never possesses, and therefore can never leak, the key that produced the signature; it only ever holds the half that can check a signature, not forge one. That single property dissolves the rotation problem the previous section named: Keycloak can rotate its signing key on its own schedule, publish the new public key at the same JWKS URL alongside the old one for an overlap window, and every verifier picks up the new key the next time its cache refreshes — no coordinated secret redeploy across every service that checks a token, because there was never a shared secret to redeploy in the first place. `JwtHs256.java`'s own Javadoc names the extension that path runs through on the Quarkus side: `quarkus-oidc`, not the hand-rolled `Mac`/`MessageDigest` pair this chapter builds specifically to make the mechanics visible.

{% include excalidraw.html file="17-hs256-vs-keycloak" alt="Two columns under a shared band captioned same bearer-JWT shape at the upgrade, different trust model behind it, DRQ-021. The left column, labeled THIS EXAMPLE teaching, shows mint_token.py slash TokenMinter -- one process mints and signs HS256, then WS_JWT_SECRET -- one symmetric key shared by every minter and verifier, drawn as an ink emphasis box, then Verify: recompute HMAC, constant-time compare against the shared secret. The right column, labeled PRODUCTION PATH Keycloak slash OIDC, shows Keycloak issues and signs RS256 token at a real OIDC token endpoint, then a JWKS endpoint publishes public keys -- resource server fetches, caches, rotates, drawn as a matching ink emphasis box, then Verify: RSA signature against the rotating public key -- no shared secret. An amber arrow runs between the two column headers labeled DRQ-021 same shape, different trust model. A caption states that a shared secret works for one teaching process minting and verifying its own tokens, but does not survive a second verifier needing the same secret." caption="Figure 17.2 -- this chapter's self-minted HS256 shared secret and the Keycloak/OIDC RS256-plus-JWKS path both put a bearer JWT at the upgrade; only the trust model behind the signature differs." %}

This is also why the signature check itself matters more than it might seem for a "just HMAC" example: pinning `algorithms=["HS256"]` in `validate_token` isn't just tidy code, it's the specific guard that prevents an attacker from presenting an RS256-signed-by-nobody-you-trust token and having a careless verifier accept it because the token's own header happened to claim `alg: HS256` and some library trusted that claim over the caller's own configuration. A production migration to Keycloak isn't a drop-in library swap for exactly this reason — the verification code has to change from "recompute and compare against a known secret" to "look up the right public key for this token's `kid` and verify against that," a different enough operation that `quarkus-oidc` (or an equivalent OIDC client library on the Python side) is worth the dependency rather than optional polish.

## wss:// is table stakes, not an optional hardening step

One more piece of this picture is easy to take for granted precisely because it's invisible in the example code: everything in `examples/part4-connection` runs over plain `ws://` — `compose.yaml` wires `localhost:8080` and `localhost:8081` with no TLS termination anywhere in the stack, because a local Docker Compose example has no certificate to present and adding one would buy nothing for the channel-level concerns this chapter is actually teaching. That's the right call for this repository's examples, and it would be exactly the wrong call for anything carrying a real bearer token across a real network. Every token this chapter mints travels as `?token=<jwt>` in the clear over `ws://` inside this example's Docker network — fine when "the network" is a loopback interface inside one Compose project, a serious problem the moment that same URL crosses an actual network boundary an attacker could observe. `wss://` (WebSocket-over-TLS) encrypts the entire upgrade request — query string, any headers, the whole HTTP exchange — the same way `https://` protects an ordinary request, which is precisely the protection a query-string-carried token depends on to make the "it's in the URL, which ends up in logs" trade-off from earlier in this chapter tolerable: a log on the server that terminates TLS still sees the plaintext URL (because TLS termination happens before the application logs the request), but anything *between* the client and that termination point — a coffee-shop Wi-Fi network, a transparent proxy, an ISP — sees nothing but encrypted bytes. Skip `wss://` and the token-in-query-string trade-off this chapter already accepts stops being "logged on servers you control" and becomes "readable by anyone positioned on the network path," which is a categorically worse exposure than this chapter's design intends.

## On the wire

Running `examples/part4-connection/verify.sh` end to end brings up both stacks under `docker compose`, mints a shared set of tokens once, and asserts identical auth behavior against each:

```bash
cd examples/part4-connection
./verify.sh
```

A live run against both stacks produced exactly the outcomes this chapter describes. A valid token gets the fixture's first frame:

```
lib.sh: quarkus first frame (valid token): {"eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
lib.sh: ok — quarkus valid-token first frame eventType: 'RECEIVE'
lib.sh: ok — quarkus valid-token first frame bookingId: 'bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A'
```

And each of the four rejection modes — no token at all, a garbage string, an expired token, and a token signed with the wrong secret — closed with no data delivered, on both stacks:

```
lib.sh: ok — quarkus: no token: ...handling-events: connection was rejected (no frame received)
lib.sh: ok — quarkus: garbage token: ...?token=not-a-jwt-at-all: connection was rejected (no frame received)
lib.sh: ok — quarkus: expired token: ...?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...: connection was rejected (no frame received)
lib.sh: ok — quarkus: bad-sig token: ...?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...: connection was rejected (no frame received)
```

```
lib.sh: ok — python: no token: ...handling-events: connection was rejected (no frame received)
lib.sh: ok — python: garbage token: ...?token=not-a-jwt-at-all: connection was rejected (no frame received)
lib.sh: ok — python: expired token: ...?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...: connection was rejected (no frame received)
lib.sh: ok — python: bad-sig token: ...?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...: connection was rejected (no frame received)
```

`verify.sh`'s probe can't observe a WebSocket close code with `websocat` reliably (both app READMEs note the limitation), so the "rejected" assertion above is `lib.sh`'s `assert_ws_rejected` helper — the same "no `101`, or an immediate post-upgrade close" check this chapter's `process_request`-vs-handler section already named as treating the two cases identically. The run finished with every assertion across both stacks (auth, the Chapter 13 error envelope, Chapter 12 backpressure, and Chapter 14 heartbeats) passing in one script:

```
PASS — Part 4 connection-concerns: Quarkus and Python both implement identical Ch17 auth (accept + 4 reject modes), Ch13 error taxonomy (BAD_REQUEST envelope + 4400 close), Ch12 backpressure (4290 close), and Ch14 heartbeat liveness detection of a silent peer (proven live on both stacks within a short, env-configured window) against the SAME shared JWT secret.
```

To mint a token by hand and inspect it — minted live against the dev-default secret, PyJWT's own `InsecureKeyLengthWarning` included because that 20-byte default is below the 32-byte minimum RFC 7518 §3.2 recommends for HS256:

```bash
cd examples/part4-connection/python
uv run python -m app.mint_token
```

```
/.../site-packages/jwt/api_jws.py:149: InsecureKeyLengthWarning: The HMAC key is 20 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0LWNsaWVudCIsImJvb2tpbmdJZCI6ImJrZ18wMUhaWTNLWDdRWko4TjZWV1QyRTRSOUYwQSIsImlhdCI6MTc5MjM4NTIwNywiZXhwIjoxNzkyMzg1NTA3fQ.31ntRnE_WFeYc2FdHRGDMhHXZvjGhVyObW8iFXDYmec
```

Three dot-separated segments: `{% raw %}eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9{% endraw %}` decodes to `{"alg":"HS256","typ":"JWT"}`, the middle segment decodes to the `sub`/`bookingId`/`iat`/`exp` claims this chapter's minters build, and the final segment is the HMAC-SHA256 signature over the first two joined by a dot — exactly the structure `JwtHs256.verify` and `validate_token` both check, segment by segment, before either one looks at a single claim.

## Where this goes next

This chapter closed the gap every other Part 4 chapter assumed shut: a connection now has to prove who's asking before it gets anything, and that check happens once, at the upgrade, on both stacks, with every failure mode collapsing to the same `1008` so a prober learns nothing from a rejection beyond "rejected." Chapter 18 picks up from an authenticated connection and asks what happens when more than one server instance exists behind a load balancer — fanning an event out to every instance holding a connection for the right booking, a problem this chapter's single-process example never had to solve. Chapters 15 and 16 already covered what a reconnecting client does after a connection drops; a reconnecting client built against this chapter's channel now also needs a fresh, unexpired token for every reconnect attempt, not just a fresh TCP connection — worth remembering if you wire Chapter 10's backoff loop against an endpoint this chapter protects. And the production path named here — Keycloak, RS256, a JWKS endpoint your resource server fetches and caches — is the thing to reach for the moment this pattern leaves a single teaching repository and needs to hand out tokens to more than one hand-rolled minter script.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Validate a bearer token at the WebSocket upgrade, not inside application logic further downstream — both stacks check it as the first thing the connection handler does, before a single frame is sent, so an unauthenticated connection never gets far enough to matter. Carry the token as a query parameter (or, if your framework makes it easier, a <code>Sec-WebSocket-Protocol</code> entry) because a browser's <code>WebSocket</code> constructor cannot attach a custom <code>Authorization</code> header — and accept the trade-off that comes with it: a token in the URL ends up in logs, so keep its TTL short and never skip <code>wss://</code>, which is what keeps that same URL unreadable to anything on the network path between client and server. Collapse every validation failure (missing, malformed, bad signature, expired) into one close code with no detail echoed to the client — the specific reason belongs in a server log, not on the wire, because a verifier that answers differently per failure mode hands a prober a signature oracle. If your WebSocket library offers a true pre-handshake rejection hook with its own close-code vocabulary, use it; if it only gives you an HTTP-response-only hook like Python's <code>websockets</code> library's <code>process_request</code>, validate immediately after accept instead and close with <code>1008</code> before sending any data — the two are observably close enough for most clients, and a WebSocket-shaped rejection is more consistent with this channel's other three connection-concern close codes than an HTTP-shaped one would be. And treat this chapter's self-minted HS256 shared secret as exactly what its own source calls it: a teaching device for a repository with no identity provider to stand up, not a production credential scheme — the production answer is Keycloak or an equivalent OIDC provider, RS256 or ES256 signatures, and a JWKS endpoint your resource server fetches and caches, so no two services ever have to already know the same secret, and a key can rotate without a coordinated redeploy across every verifier.</p></div>
