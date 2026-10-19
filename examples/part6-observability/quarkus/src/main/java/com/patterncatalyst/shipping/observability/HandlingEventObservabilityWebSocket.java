package com.patterncatalyst.shipping.observability;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import com.patterncatalyst.shipping.handlingevents.HandlingEventFeed;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.instrumentation.annotations.WithSpan;
import io.quarkus.logging.Log;
import io.quarkus.websockets.next.OnOpen;
import io.quarkus.websockets.next.PathParam;
import io.quarkus.websockets.next.WebSocket;
import io.smallrye.mutiny.Multi;
import jakarta.annotation.PostConstruct;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;

/**
 * Part 6 "Observability" example — the same {@code handlingEvents} channel
 * as part3/part4 ({@code operations.receiveHandlingEvent},
 * {@code contracts/asyncapi.yaml}: one WebSocket connection per booking,
 * replaying the shared fixture on open), now instrumented with LIVE
 * OpenTelemetry (DRQ-028) instead of connection hardening. Forked from
 * {@code examples/part3-handling-events/quarkus}'s minimal
 * {@code @OnOpen}-returns-{@code Multi<HandlingEvent>} shape — Part 6 is
 * about tracing/metrics, not backpressure/auth/heartbeats, so none of
 * part4's connection-concern machinery is reused here.
 *
 * <p>Three things happen on every connection, matching the SHARED
 * conventions the Python sibling app implements identically (verify.sh
 * asserts both uniformly):
 *
 * <ul>
 *   <li><b>Connection span</b> — {@code quarkus-opentelemetry} already
 *       auto-traces the HTTP upgrade itself (its server instrumentation
 *       covers every request, including a WebSocket upgrade). {@link WithSpan}
 *       on {@link #onOpen} ADDS a child span, {@link #CONNECTION_SPAN_NAME},
 *       that covers the fixture replay specifically — the span is already
 *       current (and child-parented under the upgrade span) by the time the
 *       method body starts executing, and the interceptor defers
 *       {@code span.end()} until the returned {@code Multi} completes (the
 *       annotation's reactive-return-type support, see the
 *       {@code opentelemetry-instrumentation-annotations} Javadoc), so the
 *       span covers the WHOLE push, not just the synchronous part of this
 *       method.</li>
 *   <li><b>Trace-id log line</b> — {@link Span#current()} is valid
 *       synchronously at the top of the method body (the {@link WithSpan}
 *       interceptor has already made it current before invoking this
 *       method), so the trace id is read and logged there, in the EXACT
 *       shape {@code verify.sh} greps for on both stacks:
 *       {@code otel.trace_id=<hex> span=ws.handling-events.connection bookingId=<id> instance=<service-name>}.</li>
 *   <li><b>Delivery counter</b> — {@link #deliveredCounter} (Micrometer ->
 *       Prometheus, DRQ-029) increments once per {@link HandlingEvent} as it
 *       is emitted from the {@code Multi}, i.e. once per event actually
 *       handed to WebSockets Next to serialize and send — NOT once per
 *       connection.</li>
 * </ul>
 */
@WebSocket(path = "/ws/v1/bookings/{bookingId}/handling-events", endpointId = "handling-events")
public class HandlingEventObservabilityWebSocket {

    /**
     * The manual span name — also the exact {@code span=} value in the
     * trace-id log line below. Shared, by convention (not by shared code),
     * with the Python sibling's equivalent manually-created span name.
     */
    public static final String CONNECTION_SPAN_NAME = "ws.handling-events.connection";

    @Inject
    HandlingEventFeed feed;

    @Inject
    MeterRegistry registry;

    /**
     * Read back from {@code quarkus.otel.service.name} (application.properties)
     * rather than duplicated as a literal here, so the {@code instance=}
     * field in the trace-id log line can never drift from the service name
     * actually attached to every exported span.
     */
    @ConfigProperty(name = "quarkus.otel.service.name")
    String serviceName;

    private Counter deliveredCounter;

    @PostConstruct
    void init() {
        deliveredCounter = Counter.builder("handling_events_delivered_total")
                .description("HandlingEvent fixture events delivered to a WebSocket client")
                .register(registry);
    }

    @OnOpen
    @WithSpan(CONNECTION_SPAN_NAME)
    public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {
        String traceId = Span.current().getSpanContext().getTraceId();
        Log.infof("otel.trace_id=%s span=%s bookingId=%s instance=%s",
                traceId, CONNECTION_SPAN_NAME, bookingId, serviceName);

        return Multi.createFrom().iterable(feed.events())
                .invoke(event -> deliveredCounter.increment());
    }
}
