package com.patterncatalyst.shipping.handlingevents.client;

import io.quarkus.logging.Log;
import io.quarkus.runtime.ShutdownEvent;
import io.quarkus.runtime.StartupEvent;
import io.quarkus.websockets.next.WebSocketConnector;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.event.Observes;
import jakarta.enterprise.inject.Instance;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.net.URI;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Owns the connection lifecycle for the {@code handlingEvents} channel: the
 * Ch10 teaching point for STATELESS reconnect. On any disconnect (clean
 * close, error, or a failed connection attempt) it schedules a retry with
 * exponential backoff, capped at {@code client.reconnect.max-delay-ms} and
 * randomized with +/- {@code client.reconnect.jitter-ratio} so that many
 * clients reconnecting to the same server after an outage don't all retry
 * in lockstep ("thundering herd").
 *
 * <p>This is deliberately NOT gap-aware: a reconnect only resumes receiving
 * NEW frames the server pushes after the upgrade completes. Any
 * {@code HandlingEvent}s recorded while this client was disconnected are
 * simply missed — this fixture-replay example always restarts the same
 * 3-event sequence from the top on a fresh connection, which is a visible
 * stand-in for that gap, not a fix for it. A durable, replayable feed
 * (Kafka-backed, letting a reconnecting client resume from its last
 * acknowledged offset) is Part 4 Ch16's job, not this chapter's.
 *
 * <p>{@link WebSocketConnector} instances are not thread-safe and must not
 * be reused across connection attempts (WebSockets Next reference guide,
 * "Client connectors"); {@code connectors.get()} obtains a fresh one for
 * every attempt.
 */
@ApplicationScoped
public class ReconnectingClient {

    @Inject
    Instance<WebSocketConnector<HandlingEventClientEndpoint>> connectors;

    @ConfigProperty(name = "client.ws.base-uri")
    String baseUriConfig;

    @ConfigProperty(name = "client.ws.booking-id")
    String bookingId;

    @ConfigProperty(name = "client.reconnect.base-delay-ms")
    long baseDelayMs;

    @ConfigProperty(name = "client.reconnect.max-delay-ms")
    long maxDelayMs;

    @ConfigProperty(name = "client.reconnect.jitter-ratio")
    double jitterRatio;

    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(runnable -> {
        Thread thread = new Thread(runnable, "handling-events-reconnect");
        thread.setDaemon(true);
        return thread;
    });
    private final AtomicInteger attempt = new AtomicInteger(0);
    private volatile boolean shuttingDown = false;

    void onStart(@Observes StartupEvent event) {
        Log.infof("handling-events client: starting — target=%s bookingId=%s", baseUriConfig, bookingId);
        connect();
    }

    void onStop(@Observes ShutdownEvent event) {
        shuttingDown = true;
        scheduler.shutdownNow();
    }

    void connect() {
        if (shuttingDown) {
            return;
        }
        try {
            URI baseUri = URI.create(baseUriConfig);
            connectors.get()
                    .baseUri(baseUri)
                    .pathParam("bookingId", bookingId)
                    .connectAndAwait();
            // Success: HandlingEventClientEndpoint#onOpen calls notifyConnected(),
            // which resets the attempt counter — no further action needed here.
        } catch (Exception e) {
            Log.warnf("handling-events client: connection attempt failed: %s", e.toString());
            scheduleReconnect();
        }
    }

    /** Called by {@link HandlingEventClientEndpoint#onOpen}. */
    void notifyConnected() {
        attempt.set(0);
        Log.info("handling-events client: connected");
    }

    /** Called by {@link HandlingEventClientEndpoint#onClose}. */
    void notifyDisconnected() {
        if (shuttingDown) {
            return;
        }
        scheduleReconnect();
    }

    private void scheduleReconnect() {
        int attemptNumber = attempt.getAndIncrement();
        long exponential = baseDelayMs * (1L << Math.min(attemptNumber, 20));
        long capped = Math.min(maxDelayMs, exponential);
        double jitterMultiplier = 1.0 + (ThreadLocalRandom.current().nextDouble() * 2 - 1) * jitterRatio;
        long delayMs = Math.max(0, Math.round(capped * jitterMultiplier));
        Log.infof("handling-events client: reconnecting in %dms (attempt %d)", delayMs, attemptNumber + 1);
        scheduler.schedule(this::connect, delayMs, TimeUnit.MILLISECONDS);
    }
}
