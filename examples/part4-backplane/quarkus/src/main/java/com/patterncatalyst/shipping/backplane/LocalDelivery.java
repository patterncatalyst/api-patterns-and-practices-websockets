package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import io.quarkus.logging.Log;
import io.quarkus.websockets.next.OpenConnections;
import io.quarkus.websockets.next.WebSocketConnection;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

/**
 * Delivers an event to every LOCAL connection (this JVM instance only)
 * watching the given booking, and logs the delivery line
 * {@code examples/part4-backplane/PROTOCOL.md}'s "Instance identity" section
 * requires: {@code delivered eventId=<id> bookingId=<id> instance=<INSTANCE_ID>}.
 *
 * <p>Every {@link Backplane} implementation ends up calling this for the
 * SAME reason: cross-instance fan-out (kafka/redis) and intra-process
 * delivery (stateless) both boil down to "push this event to whichever of
 * MY connections are watching this booking" — the only thing that differs
 * between modes is how the event GOT to this instance in the first place
 * (a direct call, a Kafka record, or a Redis Pub/Sub message).
 *
 * <p><b>Must use the non-blocking {@code sendText}, never {@code sendTextAndAwait}:</b>
 * confirmed live — {@link RedisBackplane}'s Pub/Sub message callback runs on
 * a Vert.x event-loop thread, where a blocking call throws
 * {@code IllegalStateException: The current thread cannot be blocked}. The
 * Kafka {@code @Incoming} consumer and the stateless direct-call path both
 * happen to run on a worker thread (blocking would have been safe for them),
 * but this class has no way to know which caller it's on, so it always uses
 * the non-blocking path — correct for all three callers.
 */
@ApplicationScoped
public class LocalDelivery {

    @Inject
    OpenConnections openConnections;

    @ConfigProperty(name = "instance.id", defaultValue = "quarkus")
    String instanceId;

    public void deliver(String bookingId, HandlingEvent event) {
        for (WebSocketConnection connection : openConnections.findByEndpointId(HandlingEventBackplaneWebSocket.ENDPOINT_ID)) {
            if (connection.isOpen() && bookingId.equals(connection.pathParam("bookingId"))) {
                connection.sendText(event).subscribe().with(
                        ignored -> Log.infof("delivered eventId=%s bookingId=%s instance=%s",
                                event.eventId(), bookingId, instanceId),
                        failure -> Log.errorf(failure, "failed to deliver eventId=%s bookingId=%s instance=%s",
                                event.eventId(), bookingId, instanceId));
            }
        }
    }
}
