package com.patterncatalyst.shipping.handlingevents;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.type.CollectionType;
import jakarta.annotation.PostConstruct;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.util.List;

/**
 * Loads the canonical, shared handling-event sequence once at startup and
 * serves it back in order. Byte-for-byte copy of part3/part4's feed — Part 5
 * replays the exact same three events, just over a second wire encoding (see
 * {@code HandlingEventPerformanceWebSocket}).
 *
 * <p>The source of truth is
 * {@code examples/part3-handling-events/fixtures/handling-events.json} — the
 * SAME fixture the Python/FastAPI sibling app replays. It is not committed
 * under {@code src/main/resources/} in this module; {@code pom.xml}'s
 * {@code copy-handling-events-fixture} execution copies it onto the
 * classpath (at {@code /fixtures/handling-events.json}) from a path relative
 * to this module's basedir at build time, so both a local Maven build and
 * the Containerfile's containerized build resolve the identical file without
 * duplicating it in source control.
 */
@ApplicationScoped
public class HandlingEventFeed {

    private static final String FIXTURE_RESOURCE = "/fixtures/handling-events.json";

    @Inject
    ObjectMapper objectMapper;

    private List<HandlingEvent> events;

    @PostConstruct
    void load() {
        try (InputStream in = getClass().getResourceAsStream(FIXTURE_RESOURCE)) {
            if (in == null) {
                throw new IllegalStateException(
                        "Fixture resource not found on classpath: " + FIXTURE_RESOURCE + " — expected "
                                + "pom.xml's copy-handling-events-fixture execution to have copied "
                                + "examples/part3-handling-events/fixtures/handling-events.json there "
                                + "during the generate-resources phase.");
            }
            CollectionType listOfHandlingEvent = objectMapper.getTypeFactory()
                    .constructCollectionType(List.class, HandlingEvent.class);
            events = List.copyOf(objectMapper.<List<HandlingEvent>>readValue(in, listOfHandlingEvent));
        } catch (IOException e) {
            throw new UncheckedIOException("Failed to load fixture resource: " + FIXTURE_RESOURCE, e);
        }
    }

    /** The fixture's handling events, in the exact order they appear in the file. */
    public List<HandlingEvent> events() {
        return events;
    }
}
