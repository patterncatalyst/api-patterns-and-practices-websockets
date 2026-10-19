package com.patterncatalyst.shipping.handlingevents.client;

import io.quarkus.logging.Log;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.Locale;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;

/**
 * The Ch10 teaching point: a bounded local buffer between the WebSocket
 * callback ({@link HandlingEventClientEndpoint#onMessage}, which runs on a
 * Vert.x worker thread — WebSockets Next's default blocking execution
 * model) and a separate consumer thread, with an EXPLICIT, configurable
 * policy for what happens when the consumer falls behind the server:
 *
 * <ul>
 *   <li>{@code BLOCK} (default) — {@link #offer} calls
 *       {@link BlockingQueue#put}, which blocks the calling (callback)
 *       thread until the consumer frees up space. No frame is ever lost,
 *       but a slow consumer throttles how fast this client can accept new
 *       frames from the server.</li>
 *   <li>{@code DROP_OLDEST} — {@link #offer} never blocks: when the queue
 *       is full it evicts the oldest buffered frame to make room for the
 *       newest one. The client stays responsive but can silently lose
 *       frames under sustained backpressure.</li>
 * </ul>
 *
 * Neither policy is "correct" in the abstract — it is a deliberate
 * trade-off the integrator makes per use case, which is why it is a
 * configuration property ({@code client.buffer.policy}) rather than a
 * hardcoded choice. {@code client.consumer.delay-ms} artificially slows
 * {@link #process} so the chosen policy's effect is observable in a demo.
 */
@ApplicationScoped
public class EventBuffer {

    enum Policy { BLOCK, DROP_OLDEST }

    @ConfigProperty(name = "client.buffer.capacity")
    int capacity;

    @ConfigProperty(name = "client.buffer.policy")
    String policyName;

    @ConfigProperty(name = "client.consumer.delay-ms")
    long consumerDelayMs;

    private BlockingQueue<String> queue;
    private Policy policy;
    private Thread consumerThread;
    private volatile boolean running = true;

    @PostConstruct
    void init() {
        queue = new ArrayBlockingQueue<>(capacity);
        policy = Policy.valueOf(policyName.toUpperCase(Locale.ROOT));
        Log.infof("handling-events client: buffer capacity=%d policy=%s consumerDelayMs=%d",
                capacity, policy, consumerDelayMs);
        consumerThread = new Thread(this::consumeLoop, "handling-events-consumer");
        consumerThread.setDaemon(true);
        consumerThread.start();
    }

    @PreDestroy
    void shutdown() {
        running = false;
        consumerThread.interrupt();
    }

    /** Called from the WebSocket callback thread for every inbound text frame. */
    void offer(String message) {
        switch (policy) {
            case BLOCK -> {
                try {
                    queue.put(message);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            case DROP_OLDEST -> {
                if (!queue.offer(message)) {
                    String dropped = queue.poll();
                    Log.warnf("handling-events client: buffer full (capacity=%d) — dropped oldest frame: %s",
                            capacity, dropped);
                    queue.offer(message);
                }
            }
        }
    }

    private void consumeLoop() {
        while (running) {
            try {
                String message = queue.take();
                process(message);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private void process(String message) {
        Log.infof("handling-events client: received %s", message);
        if (consumerDelayMs > 0) {
            try {
                Thread.sleep(consumerDelayMs);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }
}
