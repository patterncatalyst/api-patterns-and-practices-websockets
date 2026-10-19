package com.patterncatalyst.shipping.connection;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.patterncatalyst.shipping.handlingevents.HandlingEventFeed;
import io.quarkus.logging.Log;
import io.quarkus.websockets.next.CloseReason;
import io.quarkus.websockets.next.OnBinaryMessage;
import io.quarkus.websockets.next.OnClose;
import io.quarkus.websockets.next.OnError;
import io.quarkus.websockets.next.OnOpen;
import io.quarkus.websockets.next.OnPongMessage;
import io.quarkus.websockets.next.OnTextMessage;
import io.quarkus.websockets.next.PathParam;
import io.quarkus.websockets.next.UserData;
import io.quarkus.websockets.next.WebSocket;
import io.quarkus.websockets.next.WebSocketConnection;
import io.smallrye.mutiny.Uni;
import io.vertx.core.buffer.Buffer;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

/**
 * Part 4 "Connection Concerns" example — the same {@code handlingEvents}
 * channel as part3 ({@code operations.receiveHandlingEvent},
 * {@code contracts/asyncapi.yaml}: one WebSocket connection per booking,
 * replaying the shared fixture on open), now hardened with the four
 * connection concerns this part covers. Forked from
 * {@code examples/part3-handling-events/quarkus}; see this module's
 * README.md for the close-code-per-concern map, shared exactly with the
 * Python/{@code websockets}-library sibling app.
 *
 * <ul>
 *   <li><b>Ch17 auth</b> — {@link #onOpen}: a JWT (HS256, {@link JwtHs256})
 *       travels as a {@code ?token=} query parameter (the contract's
 *       {@code servers.local.bindings.ws}); missing, malformed, badly
 *       signed, and expired tokens are all indistinguishable to an attacker
 *       probing the channel, so they all collapse to the same
 *       {@link CloseCodes#AUTH_FAILURE} rejection, BEFORE a single fixture
 *       event is sent.</li>
 *   <li><b>Ch12 backpressure</b> — {@link #onOpen} delegates the actual
 *       replay to {@link OutboundBackpressureGuard}, which bounds the
 *       connection's outbound path.</li>
 *   <li><b>Ch13 errors</b> — {@link #onTextMessage}/{@link #onBinaryMessage}:
 *       this channel defines no client-to-server operation, so ANY client
 *       frame is a protocol error; it gets an in-band {@link ErrorEnvelope}
 *       then a {@link CloseCodes#BAD_REQUEST} close.
 *       {@link #onError} maps any other, unmapped server-side exception to
 *       {@link CloseCodes#UNEXPECTED_SERVER_ERROR}.</li>
 *   <li><b>Ch14 heartbeats</b> — WebSockets Next's built-in auto-ping
 *       ({@code quarkus.websockets-next.server.auto-ping-interval} in
 *       {@code application.properties}) keeps pings flowing OUT to every
 *       connection, but Vert.x's HTTP idle-timeout is NOT what detects a
 *       dead peer here: idle-timeout resets on any read OR write activity,
 *       and the server's own outbound ping is write activity, so a peer
 *       that never answers a single ping never trips it — idle-timeout
 *       alone cannot tell "healthy" from "silently dead" once auto-ping is
 *       on. {@link #onOpen} and {@link #onPongMessage} instead stamp
 *       {@link #LAST_PONG_AT} on {@link WebSocketConnection#userData()} on
 *       open and on every pong; {@link HeartbeatLivenessSweep} is the actual
 *       detector — a scheduled sweep that closes any connection whose last
 *       pong (or, if none has ever arrived, connection open time) is older
 *       than {@code example.heartbeat.liveness-timeout}, with
 *       {@link CloseCodes#LIVENESS_TIMEOUT}. See that class's Javadoc for
 *       why the sweep lives in its own {@code @ApplicationScoped} bean
 *       rather than here.</li>
 * </ul>
 */
@WebSocket(path = "/ws/v1/bookings/{bookingId}/handling-events", endpointId = "handling-events")
public class HandlingEventConnectionWebSocket {

    /**
     * Must match the {@code endpointId} set on the {@link WebSocket @WebSocket}
     * annotation above (annotation element values must be compile-time
     * constants, which rules out referencing this field there directly) —
     * {@link HeartbeatLivenessSweep} uses this constant to scope its sweep
     * to this endpoint's connections via
     * {@code OpenConnections#findByEndpointId} rather than every open
     * connection in the application (there is only one endpoint in this
     * example, but the sweep is written as if there could be more).
     */
    public static final String ENDPOINT_ID = "handling-events";

    /**
     * Epoch-millis timestamp of the last pong (or, from {@link #onOpen},
     * connection-open time as the initial baseline) for this connection,
     * stored per-connection via {@link WebSocketConnection#userData()} so
     * {@link HeartbeatLivenessSweep} — which runs on its own scheduler
     * thread, entirely outside this endpoint's {@code @SessionScoped}
     * context — can read it directly off the {@code WebSocketConnection}
     * instances {@code OpenConnections} hands back, with no CDI context of
     * its own required (same reasoning as {@code ConnectionLifecycleShutdown}
     * closing connections synchronously from a plain CDI observer method).
     */
    static final UserData.TypedKey<Long> LAST_PONG_AT = UserData.TypedKey.forLong("part4.lastPongAt");

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Inject
    WebSocketConnection connection;

    @Inject
    HandlingEventFeed feed;

    @Inject
    OutboundBackpressureGuard backpressureGuard;

    @ConfigProperty(name = "ws.jwt.secret")
    String jwtSecret;

    /**
     * Returns the {@code Uni<Void>} rather than sending/closing and
     * subscribing itself: {@code connection} is a {@code @SessionScoped}
     * bean, and that scope is only guaranteed active while Quarkus itself
     * drives the {@code Uni}/{@code Multi} this method returns — not inside
     * a {@code Uni} this code would otherwise subscribe to manually (its
     * completion runs later, on a raw Vert.x thread, after the scope has
     * been torn down, which fails with {@code ContextNotActiveException}).
     * See {@link OutboundBackpressureGuard}'s Javadoc for the same note.
     */
    @OnOpen
    public Uni<Void> onOpen(@PathParam String bookingId) {
        String token = QueryParams.get(connection.handshakeRequest().query(), "token");
        JwtHs256.VerificationResult auth = JwtHs256.verify(token, jwtSecret);
        if (!auth.valid()) {
            Log.warnf("handling-events connection REJECTED bookingId=%s reason=%s", bookingId, auth.reason());
            return connection.close(new CloseReason(CloseCodes.AUTH_FAILURE, "authentication failed"));
        }

        // Ch14 baseline: a peer that never answers a single ping (this
        // chapter's whole liveness scenario) would otherwise never get a
        // LAST_PONG_AT entry at all; stamping it here too means
        // HeartbeatLivenessSweep always has a starting point to measure
        // from, not just "connections that have ponged at least once".
        connection.userData().put(LAST_PONG_AT, System.currentTimeMillis());

        Log.infof("handling-events connection opened bookingId=%s subject=%s; replaying %d fixture event(s)",
                bookingId, auth.subject(), feed.events().size());
        return backpressureGuard.sendAll(connection, feed.events(), bookingId);
    }

    /**
     * Ch13 example: {@code operations.receiveHandlingEvent} defines no
     * client-to-server message on this channel, so ANY client text frame is,
     * by definition, outside the contract. Validates in the same stages as
     * the Python sibling — not text/JSON, not a JSON object, or (the only
     * remaining case, since nothing is ever accepted) a well-formed JSON
     * object anyway — purely so the logged/returned reason is specific,
     * before sending the {@link ErrorEnvelope} and closing with
     * {@link CloseCodes#BAD_REQUEST}.
     */
    @OnTextMessage
    public Uni<Void> onTextMessage(String raw) {
        String reason;
        try {
            JsonNode parsed = MAPPER.readTree(raw);
            reason = parsed.isObject()
                    ? "this channel accepts no client-to-server messages"
                    : "expected a JSON object";
        } catch (Exception e) {
            reason = "invalid JSON: " + e.getMessage();
        }
        return rejectMalformed(reason);
    }

    /** Binary frames are not defined on this channel either — same treatment as an invalid text frame. */
    @OnBinaryMessage
    public Uni<Void> onBinaryMessage(Buffer data) {
        return rejectMalformed("binary frames are not supported on this channel");
    }

    /**
     * Sends the {@link ErrorEnvelope} then closes with
     * {@link CloseCodes#BAD_REQUEST} — composed as ONE chained {@code Uni}
     * (never a manual nested {@code .subscribe()}; see {@link #onOpen}'s
     * Javadoc) so both calls run inside the single subscription Quarkus
     * itself manages for the {@code Uni<Void>} this method returns.
     */
    private Uni<Void> rejectMalformed(String reason) {
        String bookingId = connection.pathParam("bookingId");
        Log.warnf("handling-events connection bookingId=%s sent an unexpected client frame: %s", bookingId, reason);
        return connection.sendText(ErrorEnvelope.badRequest(reason))
                .chain(() -> connection.close(new CloseReason(CloseCodes.BAD_REQUEST, "malformed client message")));
    }

    /**
     * Ch14 liveness signal: every pong proves the peer is still there, so
     * this is the one place {@link #LAST_PONG_AT} actually moves forward
     * after {@link #onOpen}'s initial stamp. A healthy, spec-compliant
     * client answers WebSockets Next's auto-ping automatically at the
     * protocol level and lands here every
     * {@code quarkus.websockets-next.server.auto-ping-interval}; a peer
     * that stops answering simply stops updating this timestamp, which is
     * exactly what {@link HeartbeatLivenessSweep} checks for.
     */
    @OnPongMessage
    void onPongMessage(Buffer data) {
        connection.userData().put(LAST_PONG_AT, System.currentTimeMillis());
        Log.debugf("handling-events pong received bookingId=%s", connection.pathParam("bookingId"));
    }

    @OnClose
    void onClose(CloseReason reason) {
        Log.infof("handling-events connection closed bookingId=%s code=%d message=%s",
                connection.pathParam("bookingId"), reason.getCode(), reason.getMessage());
    }

    /**
     * Backstop for any exception not already handled directly (the auth
     * check and the malformed-message handlers above close the connection
     * themselves rather than throwing, so they never reach this method) —
     * e.g. a conversion error, or a failure surfacing from
     * {@link OutboundBackpressureGuard} that wasn't already turned into a
     * {@link CloseCodes#SLOW_CONSUMER} close.
     */
    @OnError
    public Uni<Void> onError(Throwable t) {
        String bookingId = connection.pathParam("bookingId");
        Log.errorf(t, "handling-events unexpected error bookingId=%s", bookingId);
        if (connection.isOpen()) {
            return connection.close(new CloseReason(CloseCodes.UNEXPECTED_SERVER_ERROR, "unexpected server error"));
        }
        return Uni.createFrom().voidItem();
    }
}
