package com.patterncatalyst.shipping.backplane;

/**
 * The three delivery strategies this example implements, selected at
 * runtime by the {@code backplane.mode} property ({@code BACKPLANE_MODE} env
 * var — see {@code application.properties} and
 * {@code examples/part4-backplane/PROTOCOL.md}'s "Backplane modes" section).
 *
 * <ul>
 *   <li>{@link #STATELESS} (default, Ch15/Ch18 baseline) — an injected event
 *       reaches only local connections on the instance that received the
 *       inject call; {@code afterEventId} is ignored (no history to replay
 *       from).</li>
 *   <li>{@link #KAFKA} (Ch16 resume + Ch18 fan-out) — instances share the
 *       {@code handling-events} Kafka topic, keyed by {@code bookingId}; each
 *       instance consumes every record independently (distinct consumer
 *       group per instance) and forwards to its local connections, which
 *       also powers {@code afterEventId} replay from in-memory history built
 *       from that consumption.</li>
 *   <li>{@link #REDIS} (Ch18 fan-out only) — instances share the
 *       {@code handling-events:{bookingId}} Pub/Sub channel; live fan-out
 *       with no replay — {@code afterEventId} behaves as stateless.</li>
 * </ul>
 */
public enum BackplaneMode {
    STATELESS,
    KAFKA,
    REDIS
}
