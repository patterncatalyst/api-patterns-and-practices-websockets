package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.util.List;

/**
 * Default mode (Ch15 baseline, no broker): an injected event is delivered
 * ONLY to local connections on the instance that received the inject call —
 * it is never persisted, so a client that is disconnected when the event is
 * injected loses it permanently (the visible-gap proof this part motivates
 * the backplane with). {@code afterEventId} is accepted on the query string
 * but ignored: there is no history to resume from — {@link #replayFor}
 * always returns empty (the fixture seed is sent separately and
 * unconditionally by {@link HandlingEventBackplaneWebSocket}, not through
 * this class — see {@link Backplane}'s Javadoc).
 */
@ApplicationScoped
public class StatelessBackplane implements Backplane {

    @Inject
    LocalDelivery localDelivery;

    @Override
    public List<HandlingEvent> replayFor(String bookingId, String afterEventId) {
        return List.of();
    }

    @Override
    public void publish(String bookingId, HandlingEvent event) {
        localDelivery.deliver(bookingId, event);
    }
}
