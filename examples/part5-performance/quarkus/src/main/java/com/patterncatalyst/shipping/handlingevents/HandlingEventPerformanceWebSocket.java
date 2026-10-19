package com.patterncatalyst.shipping.handlingevents;

import io.quarkus.logging.Log;
import io.quarkus.websockets.next.OnOpen;
import io.quarkus.websockets.next.PathParam;
import io.quarkus.websockets.next.WebSocket;
import io.quarkus.websockets.next.WebSocketConnection;
import io.smallrye.mutiny.Uni;
import jakarta.inject.Inject;

import java.util.List;

/**
 * Part 5 "Performance" example — the same {@code handlingEvents} channel as
 * part3/part4 ({@code operations.receiveHandlingEvent},
 * {@code contracts/asyncapi.yaml}: one WebSocket connection per booking,
 * replaying the shared fixture on open, then staying open), now with a
 * choice of TWO wire encodings negotiated via {@code Sec-WebSocket-Protocol}
 * (DRQ-026):
 *
 * <ul>
 *   <li>{@value #SUBPROTOCOL_PROTOBUF} — each {@link HandlingEvent} is sent
 *       as a Protobuf BINARY frame (opcode {@code 0x2}):
 *       {@link HandlingEventProtoMapper#toProto} then
 *       {@code .toByteArray()}.</li>
 *   <li>Anything else the client offers — {@value #SUBPROTOCOL_JSON},
 *       {@value #SUBPROTOCOL_BARE}, or no subprotocol at all — gets the
 *       original JSON TEXT frame (opcode {@code 0x1}), exactly as part3/
 *       part4 already send it.</li>
 * </ul>
 *
 * <p><b>Why this is a sequential {@code Uni<Void>} chain, not
 * {@code return Multi<...>}:</b> part3/part4 return {@code Multi<HandlingEvent>}
 * directly from {@code @OnOpen} and let WebSockets Next auto-serialize each
 * item. That only works because the Multi's declared generic type argument
 * is fixed at ONE Java type per method — confirmed by inspecting the
 * extension's own generated dispatch code
 * ({@code WebSocketEndpointBase#multiText}/{@code #multiBinary}): the
 * build-time bytecode generator picks text-vs-binary wiring from the
 * {@code @OnOpen} method's STATIC declared return type
 * ({@code Multi<Buffer>}/{@code Multi<byte[]>} &rarr; binary, anything else
 * &rarr; text-with-Jackson), not from each item's runtime type. A single
 * method cannot declare "{@code Multi<HandlingEvent>} OR
 * {@code Multi<byte[]>} depending on what this connection negotiated" — by
 * the time the method runs, the framework has already committed to one
 * dispatch path for the method's whole lifetime. Calling
 * {@link WebSocketConnection#sendText(Object)} /
 * {@link WebSocketConnection#sendBinary(byte[])} explicitly, chosen once
 * per-connection after reading {@link WebSocketConnection#subprotocol()},
 * sidesteps that entirely — both are plain {@code Sender} methods available
 * on every connection regardless of how it was opened.
 *
 * <p>Returns {@code Uni<Void>} (not {@code Multi}) for the same reason
 * part4 does: completing a {@code Uni<Void>} from {@code @OnOpen} finishes
 * the open-callback's own work without closing the connection — the
 * SHARED-CONVENTIONS requirement that this channel stays open after the
 * 3-event replay.
 */
@WebSocket(path = "/ws/v1/bookings/{bookingId}/handling-events", endpointId = "handling-events")
public class HandlingEventPerformanceWebSocket {

    /** Binary Protobuf encoding (DRQ-026) — contracts/handling-event.proto. */
    public static final String SUBPROTOCOL_PROTOBUF = "handling-events.v1+protobuf";
    /** JSON encoding, explicit form — equivalent to {@link #SUBPROTOCOL_BARE}. */
    public static final String SUBPROTOCOL_JSON = "handling-events.v1+json";
    /** JSON encoding, the original pre-Part-5 bare subprotocol value. */
    public static final String SUBPROTOCOL_BARE = "handling-events.v1";

    @Inject
    WebSocketConnection connection;

    @Inject
    HandlingEventFeed feed;

    @OnOpen
    public Uni<Void> onOpen(@PathParam String bookingId) {
        String subprotocol = connection.subprotocol();
        boolean useProtobuf = SUBPROTOCOL_PROTOBUF.equals(subprotocol);
        List<HandlingEvent> events = feed.events();

        Log.infof("handling-events connection opened bookingId=%s subprotocol=%s encoding=%s; replaying %d fixture event(s)",
                bookingId, subprotocol, useProtobuf ? "protobuf" : "json", events.size());

        Uni<Void> chain = Uni.createFrom().voidItem();
        for (HandlingEvent event : events) {
            chain = useProtobuf
                    ? chain.chain(() -> connection.sendBinary(HandlingEventProtoMapper.toProto(event).toByteArray()))
                    : chain.chain(() -> connection.sendText(event));
        }
        return chain;
    }
}
