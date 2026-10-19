package com.patterncatalyst.shipping.connection;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import io.quarkus.logging.Log;
import io.quarkus.websockets.next.CloseReason;
import io.quarkus.websockets.next.WebSocketConnection;
import io.smallrye.mutiny.Multi;
import io.smallrye.mutiny.Uni;
import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Ch12 example — server-side backpressure on the outbound push feed.
 *
 * <p>Mirrors the Python sibling's {@code app/outbound.py} bounded
 * {@code asyncio.Queue}, but WebSockets Next doesn't expose an explicit
 * outbound queue to bound: items returned from an {@code @OnOpen} / {@code
 * @OnTextMessage} {@code Multi} are written to the connection "as they are
 * emitted" (reference guide, "Supported return types"), and the only
 * documented backpressure knob,
 * {@code quarkus.websockets-next.server.max-pending-messages}, bounds
 * INBOUND messages, not outbound ones (reference guide, "Limiting the
 * number of pending messages"). So this class tracks outstanding
 * (not-yet-acknowledged) {@code sendText} calls for a single connection
 * itself, the same two signals the Python sibling checks:
 *
 * <ol>
 *   <li>too many sends are outstanding at once — the producer (here, the
 *       fixture replay) is pushing faster than the client's socket can
 *       drain, i.e. a sustained rate mismatch; and</li>
 *   <li>a single {@code sendText} call doesn't complete within
 *       {@code example.backpressure.send-timeout} — the client stopped
 *       reading entirely, so even one frame can't get out.</li>
 * </ol>
 *
 * <p>Either one applies {@code example.backpressure.policy}:
 *
 * <ul>
 *   <li>{@code CLOSE} (default) — close the connection with
 *       {@link CloseCodes#SLOW_CONSUMER} (4290) and stop sending the
 *       remaining events. The safer default: an unbounded number of slow
 *       clients each holding outstanding sends is a resource-exhaustion
 *       path.</li>
 *   <li>{@code DROP} — skip the event that would exceed the threshold, log
 *       a warning, and continue with the next one. NOT a good fit for this
 *       channel's actual semantics (a missed {@code HandlingEvent} is a
 *       correctness problem, not a supersede-by-the-next-update one) — it
 *       exists to demonstrate the trade-off, same as the Python sibling's
 *       {@code drop} policy; see README.md.</li>
 * </ul>
 *
 * <p><b>Why this returns a {@code Uni<Void>} instead of sending and
 * subscribing itself:</b> {@code WebSocketConnection} is a
 * {@code @SessionScoped} CDI bean, and that scope is only active while
 * Quarkus itself is invoking an {@code @On*} callback or driving a
 * {@code Uni}/{@code Multi} that callback RETURNS — a {@code Uni} this code
 * subscribes to manually (e.g. from inside another callback) runs its
 * completion handler later, on a raw Vert.x/Netty thread, after that scope
 * has already been torn down, which fails with
 * {@code ContextNotActiveException}. Composing everything into one
 * {@code Uni} and letting {@link HandlingEventConnectionWebSocket#onOpen}
 * {@code return} it keeps every {@code connection.sendText}/{@code close}
 * call inside the single subscription Quarkus itself manages.
 *
 * <p>The default threshold (32, matching the Python sibling's
 * {@code OUTBOUND_QUEUE_MAXSIZE}) is generous enough that this example's
 * small, fixed fixture sequence never trips it in normal operation.
 */
@ApplicationScoped
public class OutboundBackpressureGuard {

    public enum Policy {
        CLOSE, DROP
    }

    @ConfigProperty(name = "example.backpressure.max-pending-sends", defaultValue = "32")
    int maxPendingSends;

    @ConfigProperty(name = "example.backpressure.send-timeout", defaultValue = "5s")
    Duration sendTimeout;

    @ConfigProperty(name = "example.backpressure.policy", defaultValue = "CLOSE")
    Policy policy;

    /**
     * Builds (but does not subscribe to) the {@code Uni<Void>} that sends
     * every item in {@code events} to {@code connection}, applying the
     * backpressure policy as needed. The caller ({@code @OnOpen}) must
     * {@code return} this directly so Quarkus's own subscription manages
     * the {@code @SessionScoped} context for every {@code sendText}/
     * {@code close} call inside it — see the class Javadoc.
     */
    public Uni<Void> sendAll(WebSocketConnection connection, List<HandlingEvent> events, String bookingId) {
        AtomicInteger pending = new AtomicInteger(0);
        AtomicBoolean closeRequested = new AtomicBoolean(false);

        return Multi.createFrom().iterable(events)
                .onItem().transformToUniAndMerge(event -> sendOne(connection, event, bookingId, pending, closeRequested))
                .collect().asList()
                .replaceWithVoid();
    }

    private Uni<Void> sendOne(WebSocketConnection connection, HandlingEvent event, String bookingId,
            AtomicInteger pending, AtomicBoolean closeRequested) {
        if (closeRequested.get()) {
            // Another item already tripped the CLOSE policy; nothing left to do.
            return Uni.createFrom().voidItem();
        }
        if (pending.get() >= maxPendingSends) {
            return applyPolicy(connection, bookingId, closeRequested,
                    "outbound buffer exceeded (pending=" + pending.get() + " >= max=" + maxPendingSends + ")");
        }

        pending.incrementAndGet();
        return connection.sendText(event)
                .ifNoItem().after(sendTimeout).failWith(
                        () -> new TimeoutException("sendText exceeded " + sendTimeout
                                + " — peer is not draining its receive buffer"))
                .onItemOrFailure().transformToUni((v, failure) -> {
                    pending.decrementAndGet();
                    if (failure == null) {
                        return Uni.createFrom().<Void>voidItem();
                    }
                    if (failure instanceof TimeoutException) {
                        return applyPolicy(connection, bookingId, closeRequested, failure.getMessage());
                    }
                    Log.errorf(failure, "failed to send event %s to bookingId=%s", event.eventId(), bookingId);
                    return Uni.createFrom().voidItem();
                });
    }

    /**
     * Applies the configured policy for one backpressure signal:
     * {@code DROP} just logs and continues; {@code CLOSE} closes the
     * connection (only once, even if multiple in-flight sends trip the
     * condition concurrently) and reports the close itself as the
     * resulting {@code Uni}, keeping the whole operation inside one
     * composed chain.
     */
    private Uni<Void> applyPolicy(WebSocketConnection connection, String bookingId, AtomicBoolean closeRequested,
            String detail) {
        if (policy == Policy.DROP) {
            Log.warnf("outbound backpressure bookingId=%s: %s — dropping event (policy=DROP)", bookingId, detail);
            return Uni.createFrom().voidItem();
        }
        if (closeRequested.compareAndSet(false, true)) {
            Log.warnf("outbound backpressure bookingId=%s: %s — closing slow consumer (policy=CLOSE)",
                    bookingId, detail);
            return connection.close(new CloseReason(CloseCodes.SLOW_CONSUMER, "slow consumer: outbound buffer exceeded"));
        }
        return Uni.createFrom().voidItem();
    }
}
