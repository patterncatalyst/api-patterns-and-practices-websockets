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

    private CloseCodes() {
    }
}
