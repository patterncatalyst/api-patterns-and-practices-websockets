package com.patterncatalyst.shipping.connection;

import io.quarkus.logging.Log;
import io.quarkus.runtime.ShutdownEvent;
import io.quarkus.websockets.next.CloseReason;
import io.quarkus.websockets.next.OpenConnections;
import io.quarkus.websockets.next.WebSocketConnection;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.event.Observes;
import jakarta.inject.Inject;

/**
 * Closes every open connection with {@link CloseCodes#GOING_AWAY} (1001) on
 * graceful application shutdown, so a connected client sees a deliberate
 * "server going away" close rather than an abrupt socket drop (which a
 * client would otherwise see as an abnormal closure, code 1006) — the
 * Quarkus-side equivalent of the Python sibling's note that the
 * {@code websockets} library's server close defaults to 1001 for every
 * connection it is holding (see
 * {@code examples/part4-connection/python/app/ws_server.py}'s
 * {@code create_server} docstring).
 *
 * <p>Uses the blocking {@code closeAndAwait} variant rather than
 * {@code close(...).subscribe()...}: a CDI {@code ShutdownEvent} observer
 * runs synchronously on the shutdown thread, not inside a Quarkus-managed
 * WebSocket subscription, so there is no automatically-propagated
 * {@code @SessionScoped} context for a deferred completion callback to run
 * in later (see {@link OutboundBackpressureGuard}'s Javadoc for the same
 * {@code @On*}-callback-specific pitfall this sidesteps by not applying
 * here).
 */
@ApplicationScoped
public class ConnectionLifecycleShutdown {

    @Inject
    OpenConnections openConnections;

    void onShutdown(@Observes ShutdownEvent event) {
        for (WebSocketConnection connection : openConnections.listAll()) {
            if (connection.isOpen()) {
                try {
                    connection.closeAndAwait(new CloseReason(CloseCodes.GOING_AWAY, "server shutting down"));
                } catch (RuntimeException e) {
                    Log.errorf(e, "error closing connection %s during shutdown", connection.id());
                }
            }
        }
    }
}
