package com.patterncatalyst.shipping.handlingevents;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.google.protobuf.InvalidProtocolBufferException;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion.VersionFlag;
import com.networknt.schema.ValidationMessage;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import shipping.handlingevents.v1.HandlingEventOuterClass;

import java.io.IOException;
import java.nio.file.Files;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Proves the Protobuf wire encoding (DRQ-026, {@code handling-events.v1+protobuf})
 * is a faithful, SMALLER binary twin of the JSON encoding
 * {@link HandlingEventContractTest} already validates — not a separate test
 * of the generated Protobuf classes in isolation.
 *
 * <p>For every event in the shared fixture:
 * <ol>
 *   <li><b>Round-trip, not just one-way:</b> {@link HandlingEvent} &rarr;
 *       {@link HandlingEventProtoMapper#toProto} &rarr; {@code toByteArray()}
 *       &rarr; {@code parseFrom(byte[])} &rarr;
 *       {@link HandlingEventProtoMapper#fromProto} &rarr; back to a
 *       {@link HandlingEvent} record, asserted {@code equals()} the
 *       original. A lossy mapper (e.g. dropping an optional field, or
 *       mangling a timestamp string) would fail here even though the proto
 *       bytes themselves parsed fine.</li>
 *   <li><b>Same contract, same schema:</b> the round-tripped event is
 *       re-serialized to JSON and validated against
 *       {@code build/handling-event.schema.json} — the SAME schema
 *       {@link HandlingEventContractTest} uses — proving the Protobuf path
 *       produces a value shape indistinguishable from the JSON path, not
 *       merely "a value".</li>
 *   <li><b>Smaller, not just different:</b> the serialized Protobuf byte
 *       count must be strictly less than the compact (no-pretty-print) JSON
 *       byte count for the same event — this part's whole premise.</li>
 * </ol>
 */
class HandlingEventProtoRoundTripTest {

    // Same Jackson configuration as HandlingEventContractTest — this is what
    // the JSON text-frame path (HandlingEventPerformanceWebSocket's
    // `connection.sendText(event)` call) actually serializes with.
    private static final ObjectMapper MAPPER = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private static JsonSchema schema;

    @BeforeAll
    static void loadSchema() throws IOException {
        JsonNode schemaNode = MAPPER.readTree(Files.readString(HandlingEventContractTest.findSchemaFile()));
        schema = JsonSchemaFactory.getInstance(VersionFlag.V202012).getSchema(schemaNode);
    }

    @Test
    void everyFixtureEventRoundTripsThroughProtobufUnchanged() throws InvalidProtocolBufferException {
        List<HandlingEvent> events = HandlingEventContractTest.loadFixtureEvents();
        assertFalse(events.isEmpty(), "fixture must contain at least one event");

        for (HandlingEvent original : events) {
            byte[] protoBytes = HandlingEventProtoMapper.toProto(original).toByteArray();

            HandlingEventOuterClass.HandlingEvent parsed = HandlingEventOuterClass.HandlingEvent.parseFrom(protoBytes);
            HandlingEvent roundTripped = HandlingEventProtoMapper.fromProto(parsed);

            assertEquals(original, roundTripped,
                    () -> "proto round trip changed " + original.eventId());
        }
    }

    @Test
    void protobufRoundTripStillValidatesAgainstTheContractSchema() throws InvalidProtocolBufferException {
        for (HandlingEvent original : HandlingEventContractTest.loadFixtureEvents()) {
            byte[] protoBytes = HandlingEventProtoMapper.toProto(original).toByteArray();
            HandlingEvent roundTripped = HandlingEventProtoMapper.fromProto(
                    HandlingEventOuterClass.HandlingEvent.parseFrom(protoBytes));

            JsonNode node = MAPPER.valueToTree(roundTripped);
            Set<ValidationMessage> errors = schema.validate(node);
            assertTrue(errors.isEmpty(),
                    () -> "schema violations for proto-round-tripped " + original.eventId() + ": " + errors);
        }
    }

    @Test
    void protobufFrameIsSmallerThanTheEquivalentJsonFrame() throws IOException {
        for (HandlingEvent event : HandlingEventContractTest.loadFixtureEvents()) {
            int protoLength = HandlingEventProtoMapper.toProto(event).toByteArray().length;
            int jsonLength = MAPPER.writeValueAsBytes(event).length;

            assertTrue(protoLength < jsonLength,
                    () -> String.format(
                            "expected the protobuf frame for %s to be smaller than its JSON frame, got proto=%d json=%d bytes",
                            event.eventId(), protoLength, jsonLength));
        }
    }
}
