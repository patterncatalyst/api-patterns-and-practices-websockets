package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;

import java.util.List;

/**
 * One delivery strategy (stateless / kafka / redis — see {@link BackplaneMode}).
 * {@link BackplaneRouter} dispatches every call to whichever implementation
 * is active for the running instance's {@code backplane.mode}.
 *
 * <p><b>Design note (matches the Python sibling exactly — see
 * {@code examples/part4-backplane/python/README.md}'s "Design note"):</b> the
 * 3-event fixture SEED is always sent directly by
 * {@link HandlingEventBackplaneWebSocket#onOpen}, in every mode, and never
 * flows through a {@link Backplane} at all — {@link #replayFor} returns ONLY
 * backplane-sourced (injected) events, never the seed. This keeps the "a
 * fresh connection always has a deterministic baseline" guarantee unconditional
 * and independent of which mode is active, and means an {@code afterEventId}
 * that refers to a seed event (not an injected one) can never be "found" in a
 * backplane's own history — see {@link KafkaBackplane#replayFor}'s Javadoc for
 * why that's the expected, handled case rather than an edge case to avoid.
 */
public interface Backplane {

    /**
     * The INJECTED (never fixture-seed) events to replay to a freshly
     * (re)connected client, after the unconditional fixture seed and before
     * live deliveries resume — see
     * {@code examples/part4-backplane/PROTOCOL.md}'s "Resume parameter"
     * section for the exact per-mode semantics of {@code afterEventId}.
     *
     * @param bookingId    the booking being watched
     * @param afterEventId the client's {@code ?afterEventId=} query value, or
     *                     {@code null}/blank if absent
     */
    List<HandlingEvent> replayFor(String bookingId, String afterEventId);

    /**
     * Publishes an event injected via
     * {@code POST /internal/bookings/{bookingId}/handling-events} to this
     * mode's transport (local-only for stateless; the shared Kafka topic or
     * Redis channel for the broker modes).
     */
    void publish(String bookingId, HandlingEvent event);

    /**
     * Called once per connection, at {@code @OnOpen}, before {@link #replayFor}
     * — a hook for modes that need to establish something the FIRST time a
     * booking is watched (only {@link RedisBackplane} overrides this, to
     * lazily subscribe to the booking's Pub/Sub channel). No-op by default.
     */
    default void onConnect(String bookingId) {
    }
}
