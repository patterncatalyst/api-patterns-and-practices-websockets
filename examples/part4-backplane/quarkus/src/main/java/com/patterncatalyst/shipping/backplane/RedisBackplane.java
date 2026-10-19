package com.patterncatalyst.shipping.backplane;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import io.quarkus.logging.Log;
import io.quarkus.redis.datasource.ReactiveRedisDataSource;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Ch18 fan-out only (no replay): instances share the Redis Pub/Sub channel
 * {@code handling-events:{bookingId}}. Live fan-out is simpler and
 * lower-latency than the kafka mode, at the cost of durability — a message
 * published while an instance isn't subscribed (or isn't running at all) is
 * gone; there is nothing to replay from, so {@code afterEventId} is ignored
 * here exactly as in stateless mode (see
 * {@code examples/part4-backplane/PROTOCOL.md}'s "Backplane modes" section).
 *
 * <p>Events are published/received as plain JSON text on the channel — the
 * same Jackson shape as the WebSocket wire frame and the Kafka topic value —
 * using a private {@link ObjectMapper} rather than the app's managed one:
 * this class has no CDI dependency on {@code quarkus-websockets-next}'s
 * mapper, and configuring {@code java.time} serialization here explicitly
 * keeps the class self-contained and testable in isolation.
 */
@ApplicationScoped
public class RedisBackplane implements Backplane {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    @Inject
    LocalDelivery localDelivery;

    @Inject
    ReactiveRedisDataSource redis;

    /** Bookings this instance has already subscribed to (subscribe once, keep forever). */
    private final Set<String> subscribedBookings = ConcurrentHashMap.newKeySet();

    @Override
    public void onConnect(String bookingId) {
        ensureSubscribed(bookingId);
    }

    @Override
    public List<HandlingEvent> replayFor(String bookingId, String afterEventId) {
        return List.of();
    }

    @Override
    public void publish(String bookingId, HandlingEvent event) {
        String json;
        try {
            json = MAPPER.writeValueAsString(event);
        } catch (Exception e) {
            throw new IllegalStateException("failed to serialize HandlingEvent for Redis publish", e);
        }
        redis.pubsub(String.class).publish(channel(bookingId), json)
                .subscribe().with(
                        ignored -> { },
                        failure -> Log.errorf(failure, "redis publish failed bookingId=%s", bookingId));
    }

    /**
     * Subscribes this instance to the booking's channel the first time a
     * local client connects for it, forwarding every message received
     * (including ones this SAME instance published — redis Pub/Sub delivers
     * to every subscriber, publisher included) to
     * {@link LocalDelivery#deliver}. The subscription is kept for the life of
     * the application (no unsubscribe on last-disconnect) — simple and
     * correct for this example's scope; a long-running production service
     * watching many distinct bookings would want to unsubscribe when the
     * last local connection for a booking closes.
     */
    private void ensureSubscribed(String bookingId) {
        if (!subscribedBookings.add(bookingId)) {
            return;
        }
        redis.pubsub(String.class).subscribe(channel(bookingId))
                .subscribe().with(
                        message -> onMessage(bookingId, message),
                        failure -> Log.errorf(failure, "redis subscription failed bookingId=%s", bookingId));
    }

    private void onMessage(String bookingId, String json) {
        try {
            HandlingEvent event = MAPPER.readValue(json, HandlingEvent.class);
            localDelivery.deliver(bookingId, event);
        } catch (Exception e) {
            Log.errorf(e, "failed to parse redis backplane message bookingId=%s", bookingId);
        }
    }

    private static String channel(String bookingId) {
        return "handling-events:" + bookingId;
    }
}
