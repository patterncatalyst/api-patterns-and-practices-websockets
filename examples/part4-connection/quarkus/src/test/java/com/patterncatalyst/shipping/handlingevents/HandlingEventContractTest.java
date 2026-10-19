package com.patterncatalyst.shipping.handlingevents;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.type.CollectionType;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion.VersionFlag;
import com.networknt.schema.ValidationMessage;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Conformance test for {@link HandlingEvent}: every event this app would
 * emit over the wire must validate against the contract-derived JSON Schema,
 * and {@link HandlingEventType} must carry exactly the contract's 8 members.
 *
 * <p>Plain JUnit (no {@code @QuarkusTest}) — this exercises serialization of
 * the production record types, not the running WebSocket endpoint, so no
 * container bootstrap is needed. Reads the SAME classpath fixture resource
 * {@link HandlingEventFeed} loads at runtime (see that class's Javadoc for
 * how it gets onto the classpath), so this test and the app agree on what
 * "the emitted events" are.
 *
 * <p>Validates against {@code build/handling-event.schema.json}, which is a
 * generated, gitignored build artifact (DRQ-018) — run
 * {@code python3 -I scripts/extract-message-schema.py build/handling-event.schema.json}
 * from the repo root before running this test (see repo README / the
 * self-verify steps in this example's README.md).
 */
class HandlingEventContractTest {

    // Mirrors how Quarkus's quarkus-jackson-managed ObjectMapper serializes
    // java.time types in this app: ISO-8601 strings (matching the contract's
    // `format: date-time`), not epoch-timestamp numbers.
    private static final ObjectMapper MAPPER = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private static JsonSchema schema;

    @BeforeAll
    static void loadSchema() throws IOException {
        Path schemaPath = findSchemaFile();
        JsonNode schemaNode = MAPPER.readTree(Files.readString(schemaPath));
        schema = JsonSchemaFactory.getInstance(VersionFlag.V202012).getSchema(schemaNode);
    }

    /**
     * Walks upward from the current working directory looking for
     * {@code build/handling-event.schema.json}. Maven normally runs tests
     * with the module basedir as the working directory
     * ({@code examples/part3-handling-events/quarkus}), three levels below
     * the repo root — walking up (rather than hardcoding
     * {@code ../../../build/...}) keeps this test working if it's ever run
     * from a different working directory (e.g. an IDE's "run test" action).
     */
    private static Path findSchemaFile() {
        Path dir = Path.of("").toAbsolutePath();
        for (Path candidate = dir; candidate != null; candidate = candidate.getParent()) {
            Path schemaFile = candidate.resolve("build/handling-event.schema.json");
            if (Files.exists(schemaFile)) {
                return schemaFile;
            }
        }
        throw new IllegalStateException(
                "build/handling-event.schema.json not found above " + dir + " — run "
                        + "`python3 -I scripts/extract-message-schema.py build/handling-event.schema.json` "
                        + "from the repo root first.");
    }

    private static List<HandlingEvent> loadFixtureEvents() {
        try (InputStream in = HandlingEventContractTest.class.getResourceAsStream("/fixtures/handling-events.json")) {
            if (in == null) {
                throw new IllegalStateException(
                        "Fixture resource not found on classpath: /fixtures/handling-events.json — expected "
                                + "pom.xml's copy-handling-events-fixture execution to have copied "
                                + "examples/part3-handling-events/fixtures/handling-events.json there "
                                + "during the generate-resources phase.");
            }
            CollectionType listOfHandlingEvent = MAPPER.getTypeFactory()
                    .constructCollectionType(List.class, HandlingEvent.class);
            return MAPPER.readValue(in, listOfHandlingEvent);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    @Test
    void fixtureEventsValidateAgainstContractSchema() {
        List<HandlingEvent> events = loadFixtureEvents();
        assertFalse(events.isEmpty(), "fixture must contain at least one event");

        for (HandlingEvent event : events) {
            JsonNode node = MAPPER.valueToTree(event);
            Set<ValidationMessage> errors = schema.validate(node);
            assertTrue(errors.isEmpty(),
                    () -> "schema violations for " + event.eventId() + ": " + errors);
        }
    }

    @Test
    void firstFixtureEventIsTheReceiveEvent() {
        HandlingEvent first = loadFixtureEvents().get(0);
        assertEquals(HandlingEventType.RECEIVE, first.eventType());
        assertEquals("evt_01HZY3M1V8X4D7Q6B2N9C0T5E8", first.eventId());
        assertEquals("bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A", first.bookingId());
    }

    @Test
    void handlingEventTypeHasAllEightContractMembers() {
        List<String> contractMembers = List.of(
                "HANDLING_EVENT_TYPE_UNSPECIFIED", "RECEIVE", "LOAD", "UNLOAD",
                "CUSTOMS", "CLAIM", "HOLD", "DELIVERED");

        HandlingEventType[] actual = HandlingEventType.values();
        assertEquals(8, actual.length, "HandlingEventType must have exactly 8 members");

        List<String> actualNames = Arrays.stream(actual).map(Enum::name).toList();
        assertEquals(contractMembers, actualNames,
                "HandlingEventType members must match the contract's enum, in order");
    }
}
