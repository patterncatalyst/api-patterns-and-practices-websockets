package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.List;
import java.util.Locale;

/**
 * Picks the active {@link Backplane} implementation from
 * {@code backplane.mode} ({@code BACKPLANE_MODE} env var, default
 * {@code stateless}) and dispatches every call to it — the single point
 * {@link HandlingEventBackplaneWebSocket} and
 * {@link HandlingEventInjectResource} depend on, so neither has to know which
 * mode is active.
 *
 * <p>All three {@link Backplane} beans are always constructed (plain
 * {@code @ApplicationScoped} CDI beans, not conditionally enabled) — only the
 * ACTIVE one's methods are ever invoked by this router. {@link KafkaBackplane}'s
 * {@code @Incoming} channel still consumes in the background regardless of
 * the configured mode (SmallRye Reactive Messaging wires {@code @Incoming}
 * statically), which is harmless when nothing is published to that topic;
 * see this module's README for the full rationale and the
 * devservices-disabled settings in {@code application.properties} that keep
 * a stateless-mode boot from requiring a reachable Kafka/Redis.
 */
@ApplicationScoped
public class BackplaneRouter {

    @ConfigProperty(name = "backplane.mode", defaultValue = "stateless")
    String modeValue;

    @Inject
    StatelessBackplane stateless;

    @Inject
    KafkaBackplane kafka;

    @Inject
    RedisBackplane redis;

    public BackplaneMode mode() {
        return BackplaneMode.valueOf(modeValue.trim().toUpperCase(Locale.ROOT));
    }

    public void onConnect(String bookingId) {
        active().onConnect(bookingId);
    }

    public List<HandlingEvent> replayFor(String bookingId, String afterEventId) {
        return active().replayFor(bookingId, afterEventId);
    }

    public void publish(String bookingId, HandlingEvent event) {
        active().publish(bookingId, event);
    }

    private Backplane active() {
        return switch (mode()) {
            case KAFKA -> kafka;
            case REDIS -> redis;
            case STATELESS -> stateless;
        };
    }
}
