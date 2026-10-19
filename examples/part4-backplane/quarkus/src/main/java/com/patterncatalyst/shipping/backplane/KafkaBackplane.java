package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import io.quarkus.logging.Log;
import io.smallrye.reactive.messaging.kafka.api.OutgoingKafkaRecordMetadata;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.reactive.messaging.Channel;
import org.eclipse.microprofile.reactive.messaging.Emitter;
import org.eclipse.microprofile.reactive.messaging.Incoming;
import org.eclipse.microprofile.reactive.messaging.Message;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Ch16 resume + Ch18 fan-out: instances share the {@code handling-events}
 * Kafka topic, keyed by {@code bookingId} (see {@code application.properties}
 * for the connector/(de)serializer wiring and
 * {@code examples/part4-backplane/PROTOCOL.md} for the wire contract).
 *
 * <p>The topic carries ONLY injected events — the 3-event fixture seed never
 * flows through it (see {@link Backplane}'s Javadoc "Design note"), so
 * {@link #injected} below is a complete, fixture-free history.
 *
 * <p><b>Fan-out, not load-balancing:</b> each instance's
 * {@code mp.messaging.incoming.handling-events-in.group.id} is derived from
 * its own {@code INSTANCE_ID} (see {@code application.properties}), so every
 * instance has its OWN consumer group and therefore receives EVERY record on
 * the topic — the opposite of the usual "one consumer group shares the
 * partitions" pattern, deliberately: Ch18's proof needs instance A's client
 * to see an event injected through instance B, which requires A to consume
 * it too, not have it load-balanced away to some other member of a shared
 * group.
 *
 * <p><b>Replay doubles as the history store:</b> {@code auto.offset.reset=earliest}
 * means a freshly started instance replays the topic from the beginning (within
 * retention) into {@link #injected} before any client ever connects, so
 * {@link #replayFor} always has the full picture to filter by
 * {@code afterEventId} against, not just events seen since this instance's own
 * uptime began.
 */
@ApplicationScoped
public class KafkaBackplane implements Backplane {

    @Inject
    LocalDelivery localDelivery;

    @Channel("handling-events-out")
    Emitter<HandlingEvent> emitter;

    /** Injected (never fixture-seed) events seen so far, per booking, in arrival order. */
    private final Map<String, List<HandlingEvent>> injected = new ConcurrentHashMap<>();

    /** Dedup guard: a redelivered/replayed Kafka record must not be appended twice. */
    private final Map<String, Set<String>> seenEventIds = new ConcurrentHashMap<>();

    /**
     * Consumes every record on {@code handling-events} (see the class
     * Javadoc for why every instance sees every record), appends it to this
     * booking's in-memory history (if not already seen), and forwards it to
     * this instance's local connections — the SAME forwarding path used
     * regardless of whether this instance or a sibling instance is the one
     * that originally published it.
     */
    @Incoming("handling-events-in")
    public void consume(HandlingEvent event) {
        String bookingId = event.bookingId();
        Set<String> seen = seenEventIds.computeIfAbsent(bookingId, ignored -> ConcurrentHashMap.newKeySet());
        if (seen.add(event.eventId())) {
            injected.computeIfAbsent(bookingId, ignored -> new CopyOnWriteArrayList<>()).add(event);
        }
        localDelivery.deliver(bookingId, event);
    }

    @Override
    public void publish(String bookingId, HandlingEvent event) {
        Message<HandlingEvent> message = Message.of(event)
                .addMetadata(OutgoingKafkaRecordMetadata.<String>builder().withKey(bookingId).build());
        emitter.send(message);
    }

    /**
     * Snapshots this booking's injected-event history (a stable, point-in-time
     * copy — {@link CopyOnWriteArrayList}'s backing array is captured whole, so
     * concurrent appends from {@link #consume} during this method never leak a
     * partially-built list into the search below) and searches it for
     * {@code afterEventId}:
     *
     * <ul>
     *   <li>absent/blank {@code afterEventId} — no replay; the client gets the
     *       fixture seed (sent separately) plus the live tail from here on.</li>
     *   <li>found — replay the suffix strictly after it, so nothing the client
     *       already saw is resent.</li>
     *   <li><b>not found — replay the ENTIRE snapshot.</b> This is the expected
     *       outcome whenever {@code afterEventId} names a FIXTURE event (the
     *       Ch15 gap scenario: a client's last-seen id, right after connecting,
     *       is one of the 3 seed events) — fixture ids never appear in this
     *       buffer at all, so the search always misses for them, and "the
     *       client's last known state predates anything this topic has ever
     *       carried" correctly means "replay everything", not "replay
     *       nothing".</li>
     * </ul>
     */
    @Override
    public List<HandlingEvent> replayFor(String bookingId, String afterEventId) {
        List<HandlingEvent> snapshot = List.copyOf(injected.getOrDefault(bookingId, List.of()));
        if (afterEventId == null || afterEventId.isBlank()) {
            return List.of();
        }

        int index = -1;
        for (int i = 0; i < snapshot.size(); i++) {
            if (snapshot.get(i).eventId().equals(afterEventId)) {
                index = i;
                break;
            }
        }
        if (index < 0) {
            Log.infof("afterEventId=%s not found in injected history for bookingId=%s "
                            + "(expected when it names a fixture-seed event); replaying all %d injected event(s)",
                    afterEventId, bookingId, snapshot.size());
            return snapshot;
        }
        return List.copyOf(snapshot.subList(index + 1, snapshot.size()));
    }
}
