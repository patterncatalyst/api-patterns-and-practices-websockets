package com.patterncatalyst.shipping.backplane;

/**
 * WebSocket close codes used by this example — a deliberately small subset
 * of part4-connection's close-code table (see
 * {@code examples/part4-backplane/PROTOCOL.md}'s "Close codes" section): this
 * part focuses on the backplane, not re-exercising auth/backpressure/liveness.
 */
public final class CloseCodes {

    /** RFC 6455 going away — graceful application shutdown ({@link ConnectionLifecycleShutdown}). */
    public static final int GOING_AWAY = 1001;

    /**
     * Application-range close (4000-4999) — a client text/binary frame on a
     * channel that defines none (same reasoning as part4-connection's
     * {@code CloseCodes#BAD_REQUEST}).
     */
    public static final int BAD_REQUEST = 4400;

    /** RFC 6455 unexpected condition — an unmapped server-side exception. */
    public static final int UNEXPECTED_SERVER_ERROR = 1011;

    private CloseCodes() {
    }
}
