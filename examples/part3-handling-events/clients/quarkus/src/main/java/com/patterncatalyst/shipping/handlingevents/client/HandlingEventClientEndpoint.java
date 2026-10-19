package com.patterncatalyst.shipping.handlingevents.client;

import io.quarkus.logging.Log;
import io.quarkus.websockets.next.OnClose;
import io.quarkus.websockets.next.OnError;
import io.quarkus.websockets.next.OnOpen;
import io.quarkus.websockets.next.OnTextMessage;
import io.quarkus.websockets.next.WebSocketClient;
import jakarta.inject.Inject;

/**
 * The CLIENT side of {@code operations.receiveHandlingEvent}
 * (contracts/asyncapi.yaml): consumes the same
 * {@code /ws/v1/bookings/{bookingId}/handling-events} channel either server
 * in this example implements (../../quarkus or ../../python — point
 * {@code client.ws.base-uri} at either one; see application.properties).
 *
 * <p>Received frames are NOT parsed into a typed model here — this client
 * stays schema-agnostic on purpose (it works unmodified against either
 * stack's wire output) and just hands the raw JSON text to {@link
 * EventBuffer}, which is the actual Ch10 teaching point (bounded buffer +
 * explicit backpressure policy). Connection lifecycle (reconnect with
 * backoff) is {@link ReconnectingClient}'s job; this class only reports
 * lifecycle events to it.
 */
@WebSocketClient(path = "/ws/v1/bookings/{bookingId}/handling-events")
public class HandlingEventClientEndpoint {

    @Inject
    ReconnectingClient lifecycle;

    @Inject
    EventBuffer buffer;

    @OnOpen
    void onOpen() {
        lifecycle.notifyConnected();
    }

    @OnTextMessage
    void onMessage(String message) {
        buffer.offer(message);
    }

    @OnClose
    void onClose() {
        Log.info("handling-events client: connection closed");
        lifecycle.notifyDisconnected();
    }

    @OnError
    void onError(Throwable t) {
        // @OnClose fires for most failure modes too (the connection tears
        // down), so reconnect scheduling stays centralized there. This
        // handler exists so a transport-level error is visible in the log
        // even when a close frame is never exchanged.
        Log.warnf("handling-events client: error: %s", t.toString());
    }
}
