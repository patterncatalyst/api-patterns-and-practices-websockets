package com.patterncatalyst.shipping.connection;

import io.quarkus.logging.Log;
import io.quarkus.scheduler.Scheduled;
import io.quarkus.scheduler.Scheduled.ConcurrentExecution;
import io.quarkus.websockets.next.CloseReason;
import io.quarkus.websockets.next.OpenConnections;
import io.quarkus.websockets.next.UserData;
import io.quarkus.websockets.next.WebSocketConnection;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.time.Duration;
import java.time.Instant;

/**
 * Ch14 example — the ACTUAL dead-peer detector for the {@code
 * handlingEvents} channel. WebSockets Next's auto-ping
 * ({@code quarkus.websockets-next.server.auto-ping-interval}) keeps the
 * server sending pings, but Vert.x's HTTP idle-timeout
 * ({@code quarkus.http.idle-timeout}) does NOT reliably detect a peer that
 * never answers one: idle-timeout resets on any read OR write activity, and
 * the server's own outbound ping is write activity on that same connection
 * — so the server keeps resetting its own idle clock every
 * {@code auto-ping-interval} regardless of whether the peer ever responds.
 * A genuinely silent peer can stay "not idle" indefinitely. (Confirmed
 * live: see {@code examples/part4-connection/verify.sh}'s Ch14 stage.)
 *
 * <p>This class closes that gap with an explicit, pong-tracked liveness
 * check instead of relying on any transport-level idle timer:
 *
 * <ol>
 *   <li>{@link HandlingEventConnectionWebSocket#onOpen} and {@code
 *       #onPongMessage} stamp {@link HandlingEventConnectionWebSocket#LAST_PONG_AT}
 *       — epoch millis — on {@link WebSocketConnection#userData()} on open
 *       and on every pong;</li>
 *   <li>this bean's {@link #sweep()} runs every
 *       {@code example.heartbeat.sweep-interval} and REQUESTS a close
 *       ({@link CloseCodes#LIVENESS_TIMEOUT}) on any connection on this
 *       endpoint whose last pong (or connection-open time, if none has ever
 *       arrived) is older than {@code example.heartbeat.liveness-timeout}.</li>
 * </ol>
 *
 * <p><b>"Requests" a close, not "completes" one:</b> closing a WebSocket is
 * itself a two-way handshake — the server sends a close frame and then
 * waits for the peer's own close frame in return before tearing down the
 * TCP connection. A peer this sweep has just proven is NOT responding
 * obviously won't send that acknowledgment either, so Vert.x falls back to
 * forcibly terminating the connection once
 * {@code HttpServerOptions.DEFAULT_WEBSOCKET_CLOSING_TIMEOUT} (10s — a
 * Vert.x-level default, not currently exposed as a Quarkus config property)
 * elapses with no reply — confirmed live: {@code onClose} observes the
 * connection's own final {@code CloseReason} as code {@code 1006}
 * (abnormal closure) in that case, not {@link CloseCodes#LIVENESS_TIMEOUT},
 * because the close this class requested never actually completed the
 * handshake. This is standard WebSocket protocol behavior for a peer that
 * stops responding entirely, not a bug in this class — a close code can
 * only reach a peer that is still reading. {@code verify.sh}'s Ch14 stage
 * budgets its wait for this ~10s grace on top of
 * {@code example.heartbeat.liveness-timeout}.
 *
 * <p>Because that grace period can leave a connection in a
 * neither-open-nor-fully-closed state for up to ~10s, {@link #sweep()}
 * stamps {@link #CLOSE_REQUESTED} on the connection the moment it requests
 * a close, and skips any connection already marked — otherwise every
 * subsequent tick of this sweep (every {@code sweep-interval}, by default
 * far shorter than that 10s grace) would re-request a close on the same
 * still-draining connection. For the same reason, closing uses the
 * non-blocking {@link WebSocketConnection#close(CloseReason)} (subscribed
 * to, not awaited) rather than {@code closeAndAwait}: blocking this
 * method's thread for up to 10s per dead connection would stall the sweep
 * for every OTHER connection it still needs to check in the same run.
 * {@code concurrentExecution = SKIP} is an additional backstop against
 * overlapping sweep runs piling up while any single run is in flight.
 *
 * <p><b>Why a separate scheduled bean instead of logic inside the
 * endpoint:</b> {@code HandlingEventConnectionWebSocket} is only invoked BY
 * Quarkus, for ONE connection at a time, while that connection's
 * {@code @SessionScoped} {@code WebSocketConnection} context is active (see
 * that class's and {@link OutboundBackpressureGuard}'s Javadoc). A liveness
 * sweep is the opposite shape: it needs to run on its own schedule, look
 * across EVERY open connection at once, and keep running whether or not any
 * particular connection's session context happens to be active at that
 * moment. A {@code @Scheduled} method runs on its own worker thread with no
 * WebSocket session context at all — exactly the same situation
 * {@code ConnectionLifecycleShutdown}'s {@code @Observes ShutdownEvent}
 * method is already in, which is why this class follows its lead: read the
 * live connections straight off the injected {@link OpenConnections}
 * registry (no {@code @Inject WebSocketConnection} field — that would
 * resolve to whatever connection happens to be active for the CURRENT
 * request, which is meaningless on a scheduler thread) and call
 * {@code connection.close(...)} directly on each one, rather than
 * returning/subscribing to a {@code Uni} that would need a session context
 * to run in.
 */
@ApplicationScoped
public class HeartbeatLivenessSweep {

    /**
     * Marks a connection this sweep has already requested a close on, so a
     * later tick (which runs well inside the ~10s Vert.x closing-handshake
     * grace described above) doesn't re-request it. See the class Javadoc.
     */
    private static final UserData.TypedKey<Boolean> CLOSE_REQUESTED =
            UserData.TypedKey.forBoolean("part4.heartbeatCloseRequested");

    @Inject
    OpenConnections openConnections;

    /**
     * How long a connection may go without a pong before it's considered
     * dead. Default 45s = this app's 20s {@code auto-ping-interval} * 2 +
     * 5s grace (room for one missed/delayed pong before acting, so a
     * momentary scheduling hiccup under load doesn't trip a false
     * positive). Override via {@code EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT}
     * with a short value (e.g. {@code 5s}, alongside a short
     * {@code auto-ping-interval}) to exercise this deterministically in a
     * test — see {@code examples/part4-connection/verify.sh}'s Ch14 stage.
     */
    @ConfigProperty(name = "example.heartbeat.liveness-timeout", defaultValue = "45s")
    Duration livenessTimeout;

    /**
     * Builds (but does not itself schedule with a hardcoded value) the
     * sweep's run frequency via a property expression, so
     * {@code EXAMPLE_HEARTBEAT_SWEEP_INTERVAL} can shrink it for a fast
     * test without a second config property to thread through by hand. 5s
     * default: fine-grained enough that the 45s default
     * {@code livenessTimeout} above is enforced promptly, far coarser than
     * the per-connection cost of tracking pongs would ever require at this
     * example's scale.
     */
    @Scheduled(every = "${example.heartbeat.sweep-interval:5s}", concurrentExecution = ConcurrentExecution.SKIP)
    void sweep() {
        Instant now = Instant.now();
        for (WebSocketConnection connection : openConnections.findByEndpointId(HandlingEventConnectionWebSocket.ENDPOINT_ID)) {
            if (!connection.isOpen() || Boolean.TRUE.equals(connection.userData().get(CLOSE_REQUESTED))) {
                continue;
            }
            Instant lastSeen = lastSeen(connection);
            Duration silentFor = Duration.between(lastSeen, now);
            if (silentFor.compareTo(livenessTimeout) > 0) {
                String bookingId = connection.pathParam("bookingId");
                Log.warnf("handling-events connection bookingId=%s silent for %s (>%s) — requesting close as dead (Ch14 liveness timeout)",
                        bookingId, silentFor, livenessTimeout);
                connection.userData().put(CLOSE_REQUESTED, true);
                connection.close(new CloseReason(CloseCodes.LIVENESS_TIMEOUT, "no pong received within the liveness window"))
                        .subscribe().with(
                                v -> Log.debugf("handling-events connection %s close completed after liveness timeout", connection.id()),
                                failure -> Log.errorf(failure, "error closing unresponsive connection %s during liveness sweep", connection.id()));
            }
        }
    }

    /**
     * {@link HandlingEventConnectionWebSocket#LAST_PONG_AT} is always
     * stamped at {@code @OnOpen}, so the fallback to
     * {@link WebSocketConnection#creationTime()} below is a defensive-only
     * path for the brief window between a connection appearing in
     * {@link OpenConnections} (right after the HTTP upgrade completes) and
     * {@code @OnOpen} finishing its own {@code userData()} write — never
     * observed to matter at this example's scale, but cheap insurance
     * against ever treating "just connected, @OnOpen hasn't run yet" as
     * "already overdue".
     */
    private static Instant lastSeen(WebSocketConnection connection) {
        Long lastPongMillis = connection.userData().get(HandlingEventConnectionWebSocket.LAST_PONG_AT);
        return lastPongMillis != null ? Instant.ofEpochMilli(lastPongMillis) : connection.creationTime();
    }
}
