package com.patterncatalyst.shipping.backplane;

import com.patterncatalyst.shipping.handlingevents.HandlingEvent;
import io.quarkus.kafka.client.serialization.ObjectMapperDeserializer;

/** Kafka value deserializer counterpart to {@link HandlingEventSerializer}. */
public class HandlingEventDeserializer extends ObjectMapperDeserializer<HandlingEvent> {

    public HandlingEventDeserializer() {
        super(HandlingEvent.class);
    }
}
