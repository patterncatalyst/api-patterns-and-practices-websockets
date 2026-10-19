package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import com.patterncatalyst.shipping.handlingevents.HandlingEventFeed;
import io.quarkus.logging.Log;
import io.quarkus.websockets.next.CloseReason;
import io.quarkus.websockets.next.OnBinaryMessage;
import io.quarkus.websockets.next.OnClose;
import io.quarkus.websockets.next.OnError;
import io.quarkus.websockets.next.OnOpen;
import io.quarkus.websockets.next.OnTextMessage;
import io.quarkus.websockets.next.PathParam;
import io.quarkus.websockets.next.WebSocket;
import io.quarkus.websockets.next.WebSocketConnection;
import io.smallrye.mutiny.Multi;
import io.smallrye.mutiny.Uni;
import io.vertx.core.buffer.Buffer;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.ArrayList;
import java.util.List;

/**
 * Implements {@code operations.receiveHandlingEvent} from
 * {@code contracts/asyncapi.yaml} — same channel as part3/part4-connection —
 * per {@code examples/part4-backplane/PROTOCOL.md}: one WebSocket connection
 * per booking. {@code @OnOpen} sends TWO things back to back, from two
 * different sources (see {@link Backplane}'s Javadoc "Design note" for why
 * this split matches the Python sibling exactly): the 3-event fixture seed,
 * directly from {@link HandlingEventFeed}, unconditionally, in every mode;
 * then whatever {@link BackplaneRouter#replayFor} returns for the active
 * mode's {@code afterEventId} handling (kafka only — stateless/redis always
 * return empty). The connection then continues to receive live deliveries
 * for its lifetime.
 *
 * <p>Unlike part3/part4-connection's {@code @OnOpen}, the "continue live"
 * half of this channel is NOT expressed as a longer-lived {@code Multi}: the
 * initial seed+replay burst is returned as a {@code Multi} (so WebSockets
 * Next sends it in order, same mechanism as part3), but every live event
 * AFTER that burst is pushed later, from an entirely different call site —
 * {@link LocalDelivery#deliver}, invoked by whichever {@link Backplane} mode
 * is active when an event arrives (a direct local call, a Kafka
 * {@code @Incoming} consumer, or a Redis Pub/Sub callback) — using the same
 * {@link WebSocketConnection} reference obtained from {@code OpenConnections},
 * exactly like cross-endpoint broadcasting. This is simpler than merging two
 * {@code Multi}s into one stream and is the natural shape for "a handful of
 * ordered history items, then an open-ended stream of future pushes from code
 * that doesn't run inside THIS method's subscription".
 */
@WebSocket(path = "/ws/v1/bookings/{bookingId}/handling-events", endpointId = HandlingEventBackplaneWebSocket.ENDPOINT_ID)
public class HandlingEventBackplaneWebSocket {

    /** Must match the {@code endpointId} above — see {@link LocalDelivery}. */
    public static final String ENDPOINT_ID = "handling-events";

    @Inject
    WebSocketConnection connection;

    @Inject
    BackplaneRouter router;

    @Inject
    HandlingEventFeed feed;

    @ConfigProperty(name = "instance.id", defaultValue = "quarkus")
    String instanceId;

    /**
     * The 3-event fixture seed is sent directly from {@link #feed} here,
     * UNCONDITIONALLY and in every mode — it never flows through a
     * {@link Backplane} at all (see {@link Backplane}'s Javadoc "Design
     * note", which matches the Python sibling exactly). Only the events
     * AFTER that seed — the mode-specific {@code afterEventId} replay, then
     * the live tail — come from {@link BackplaneRouter}.
     */
    @OnOpen
    public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {
        String afterEventId = QueryParams.get(connection.handshakeRequest().query(), "afterEventId");
        router.onConnect(bookingId);
        List<HandlingEvent> replay = router.replayFor(bookingId, afterEventId);

        List<HandlingEvent> initial = new ArrayList<>(feed.events().size() + replay.size());
        initial.addAll(feed.events());
        initial.addAll(replay);

        Log.infof("handling-events connection opened bookingId=%s afterEventId=%s mode=%s instance=%s; "
                        + "seeding %d fixture event(s) + replaying %d backplane event(s)",
                bookingId, afterEventId, router.mode(), instanceId, feed.events().size(), replay.size());

        return Multi.createFrom().iterable(initial)
                .onItem().invoke(event ->
                        Log.infof("delivered eventId=%s bookingId=%s instance=%s", event.eventId(), bookingId, instanceId));
    }

    /**
     * This channel defines no client-to-server operation (same as
     * part3/part4-connection) — any client frame is, by definition, outside
     * the contract; close immediately rather than sending an in-band error
     * envelope (that Ch13 nuance is part4-connection's concern, out of scope
     * here — see PROTOCOL.md's "Close codes" section).
     */
    @OnTextMessage
    public Uni<Void> onTextMessage(String raw) {
        return rejectMalformed();
    }

    @OnBinaryMessage
    public Uni<Void> onBinaryMessage(Buffer data) {
        return rejectMalformed();
    }

    private Uni<Void> rejectMalformed() {
        String bookingId = connection.pathParam("bookingId");
        Log.warnf("handling-events connection bookingId=%s sent an unexpected client frame", bookingId);
        return connection.close(new CloseReason(CloseCodes.BAD_REQUEST, "malformed client message"));
    }

    @OnClose
    void onClose(CloseReason reason) {
        Log.infof("handling-events connection closed bookingId=%s code=%d message=%s instance=%s",
                connection.pathParam("bookingId"), reason.getCode(), reason.getMessage(), instanceId);
    }

    @OnError
    public Uni<Void> onError(Throwable t) {
        String bookingId = connection.pathParam("bookingId");
        Log.errorf(t, "handling-events unexpected error bookingId=%s instance=%s", bookingId, instanceId);
        if (connection.isOpen()) {
            return connection.close(new CloseReason(CloseCodes.UNEXPECTED_SERVER_ERROR, "unexpected server error"));
        }
        return Uni.createFrom().voidItem();
    }
}
