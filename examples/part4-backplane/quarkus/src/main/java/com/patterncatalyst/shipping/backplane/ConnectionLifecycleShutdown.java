package com.patterncatalyst.shipping.backplane;

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
 * graceful application shutdown — forked verbatim from
 * {@code examples/part4-connection/quarkus}'s class of the same name; see
 * that class's Javadoc for why {@code closeAndAwait} (not a subscribed
 * {@code close(...)}) is used from a plain {@code ShutdownEvent} observer.
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
