package com.patterncatalyst.shipping.handlingevents;

import io.quarkus.logging.Log;
import io.quarkus.websockets.next.OnOpen;
import io.quarkus.websockets.next.PathParam;
import io.quarkus.websockets.next.WebSocket;
import io.smallrye.mutiny.Multi;
import jakarta.inject.Inject;

/**
 * Implements {@code operations.receiveHandlingEvent} from
 * {@code contracts/asyncapi.yaml}: one WebSocket connection per booking,
 * server-to-client push only — the server never expects a client-to-server
 * message on this channel, so there is no {@code @OnTextMessage} here.
 *
 * <p>Returning {@code Multi<HandlingEvent>} from {@code @OnOpen} establishes
 * a persistent server-push stream for the connection's lifetime (WebSockets
 * Next reference guide, "Streams"); each emitted item is serialized to JSON
 * and sent as one text frame, in emission order. This chapter's example
 * replays the fixed, shared fixture — {@link HandlingEventFeed} — rather
 * than a live event source, which lands in a later chapter.
 */
@WebSocket(path = "/ws/v1/bookings/{bookingId}/handling-events")
public class HandlingEventWebSocket {

    @Inject
    HandlingEventFeed feed;

    @OnOpen
    public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {
        Log.infof("handling-events connection opened for bookingId=%s; replaying %d fixture event(s)",
                bookingId, feed.events().size());
        return Multi.createFrom().iterable(feed.events());
    }
}
