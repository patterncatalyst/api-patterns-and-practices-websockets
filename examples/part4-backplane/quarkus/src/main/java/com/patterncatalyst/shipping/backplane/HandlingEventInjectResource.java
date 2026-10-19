package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import io.quarkus.logging.Log;
import jakarta.inject.Inject;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.core.Response;

/**
 * {@code POST /internal/bookings/{bookingId}/handling-events} — how tests
 * (and Ch18 itself) inject an event onto the active backplane, per
 * {@code examples/part4-backplane/PROTOCOL.md}'s "Inject endpoint" section.
 * NOT part of the public {@code contracts/asyncapi.yaml} contract — an
 * internal/demo endpoint only, documented here and in the module README.
 *
 * <p>Delegates to {@link BackplaneRouter#publish}, which routes to the
 * active mode: local-only delivery in stateless mode, or a publish onto the
 * shared Kafka topic / Redis channel in the broker modes. Always returns
 * {@code 202 Accepted} — publishing is fire-and-forget from the caller's
 * perspective (the inject request does not wait for any connected client to
 * actually receive the event).
 */
@Path("/internal/bookings/{bookingId}/handling-events")
public class HandlingEventInjectResource {

    @Inject
    BackplaneRouter router;

    @POST
    public Response inject(@PathParam("bookingId") String bookingId, HandlingEvent event) {
        Log.infof("inject bookingId=%s eventId=%s mode=%s", bookingId, event.eventId(), router.mode());
        router.publish(bookingId, event);
        return Response.status(Response.Status.ACCEPTED).build();
    }
}
