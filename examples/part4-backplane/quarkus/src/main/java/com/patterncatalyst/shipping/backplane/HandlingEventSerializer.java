package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import io.quarkus.kafka.client.serialization.ObjectMapperSerializer;

/**
 * Kafka value serializer for the {@code handling-events} topic (kafka
 * backplane mode). {@link ObjectMapperSerializer} (from
 * {@code quarkus-kafka-client}, pulled in transitively by
 * {@code quarkus-messaging-kafka}) uses the application's managed Jackson
 * {@code ObjectMapper} — the same one {@code quarkus-websockets-next}
 * already uses to serialize {@link HandlingEvent} to the WebSocket frame, so
 * the wire shape on the topic matches the wire shape on the channel exactly.
 */
public class HandlingEventSerializer extends ObjectMapperSerializer<HandlingEvent> {
}
