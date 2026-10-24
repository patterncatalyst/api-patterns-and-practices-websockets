package com.patterncatalyst.shipping.connection;

/**
 * WebSocket close codes used across this example (Part 4 "Connection
 * Concerns"), matching the Python/{@code websockets}-library sibling app
 * exactly (see {@code examples/part4-connection/python/app/ws_server.py})
 * so a client sees identical close semantics regardless of which stack it
 * talks to.
 *
 * <p><b>Close-code-vs-error-envelope choice (Ch13):</b> a close code alone
 * tells a client THAT something went wrong and, for the two application
 * codes below, roughly what category — but it carries no human-readable
 * detail and arrives only as the socket is going away, which is too late
 * for a client developer to see anything more useful than "it closed". The
 * in-band JSON {@link ErrorEnvelope} is sent FIRST, while the connection is
 * still open, so the client's normal message handler sees a structured,
 * readable reason; the close code that follows immediately after is the
 * cheap, payload-free signal an automated reconnect loop can key off
 * without parsing a frame. This example sends both for the one case that
 * has a specific offending message to annotate ({@link #BAD_REQUEST}); the
 * other three codes close before any data has been streamed on the
 * connection (auth, backpressure) or after the connection is already in an
 * unknown state (an unmapped server exception), so there is no established
 * protocol moment in which an envelope would make sense — the close code
 * alone is the signal.
 */
public final class CloseCodes {

    /** RFC 6455 policy violation — JWT auth failure at {@code @OnOpen} (Ch17). */
    public static final int AUTH_FAILURE = 1008;

    /**
     * Application-range close (4000-4999, so it can't be confused with an
     * RFC 6455 standard code) — a client text/binary frame outside the
     * contract (Ch13). Always preceded by an {@link ErrorEnvelope}.
     */
    public static final int BAD_REQUEST = 4400;

    /** Application-range close — the outbound backpressure policy's CLOSE action (Ch12). */
    public static final int SLOW_CONSUMER = 4290;

    /** RFC 6455 unexpected condition — an unmapped server-side exception (Ch13). */
    public static final int UNEXPECTED_SERVER_ERROR = 1011;

    /** RFC 6455 going away — used on graceful application shutdown (see {@code ConnectionLifecycleShutdown}). */
    public static final int GOING_AWAY = 1001;

    /**
     * Application-range close — a connection whose peer stopped answering
     * pings, detected by {@link HeartbeatLivenessSweep} (Ch14). Deliberately
     * its OWN code rather than reusing {@link #GOING_AWAY} (that one means
     * "the SERVER is shutting down", a different event) or
     * {@link #UNEXPECTED_SERVER_ERROR} (that one means "an unmapped
     * exception", not "the peer went silent") — a client-side reconnect loop
     * that distinguishes these three needs three different codes. Named
     * after HTTP 408 Request Timeout for the same "the other side stopped
     * responding" mnemonic, moved into the app range so it can't be confused
     * with an RFC 6455 standard code.
     *
     * <p>The Python/{@code websockets}-library sibling app does NOT use this
     * exact numeric value: that library's own keepalive mechanism closes
     * with its own hardcoded 1011 ("keepalive ping timeout") when a ping
     * goes unanswered, and wrapping that default to emit a matching
     * app-range code is out of scope for this chapter (see that app's
     * README's Ch14 section). The two stacks therefore agree on when a
     * silent peer is closed, but not on the exact close code; documented
     * here rather than silently left inconsistent.
     */
    public static final int LIVENESS_TIMEOUT = 4408;

    private CloseCodes() {
    }
}
