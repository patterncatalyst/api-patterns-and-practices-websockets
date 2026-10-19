package com.patterncatalyst.shipping.handlingevents;

import shipping.handlingevents.v1.HandlingEventOuterClass;

/**
 * Converts between {@link HandlingEvent} (this app's record, serialized to
 * JSON by Jackson for the {@code handling-events.v1+json} subprotocol) and
 * {@code shipping.handlingevents.v1.HandlingEventOuterClass.HandlingEvent}
 * (the Java class {@code io.github.ascopes:protobuf-maven-plugin} generates
 * from {@code contracts/handling-event.proto}, serialized to Protobuf binary
 * for {@code handling-events.v1+protobuf}) — see
 * {@code HandlingEventPerformanceWebSocket} for where each path is chosen.
 *
 * <p><b>Why the outer class name:</b> {@code handling-event.proto} declares
 * no {@code option java_outer_classname}, so {@code protoc} derives one from
 * the file name ({@code handling-event.proto} &rarr; {@code HandlingEvent}).
 * That collides with the {@code HandlingEvent} message itself declared
 * inside the same file, so {@code protoc} falls back to its standard
 * collision-avoidance rule and appends {@code OuterClass}
 * ({@code HandlingEventOuterClass}), nesting the message as
 * {@code HandlingEventOuterClass.HandlingEvent} — confirmed by inspecting
 * the actual generated source under {@code target/generated-sources/}.
 * {@code contracts/handling-event.proto} is shared, parity-gated
 * infrastructure (also consumed by the Python sibling's grpcio-tools
 * generation); adding a Java-only {@code java_outer_classname} option there
 * purely to shorten a name used in exactly one file here was judged not
 * worth touching shared, governed infrastructure for.
 *
 * <p><b>Enum mapping:</b> {@link HandlingEventType}'s members are the bare
 * contract wire values ({@code RECEIVE}, {@code LOAD}, ...); the proto
 * enum's members carry the same values under an additional
 * {@code HANDLING_EVENT_TYPE_} prefix (buf's {@code ENUM_VALUE_PREFIX} lint
 * rule) — {@code scripts/check-proto-parity.py} already asserts these two
 * enums agree after that prefix is stripped; this class performs the exact
 * same string transform at runtime.
 *
 * <p><b>Field value equality:</b> {@code occurredAt}/{@code registeredAt}
 * are mapped via {@link java.time.Instant#toString()} — the same ISO-8601
 * (RFC-3339) representation Jackson's {@code JavaTimeModule} produces for an
 * {@code Instant} with {@code WRITE_DATES_AS_TIMESTAMPS} disabled (both use
 * {@link java.time.format.DateTimeFormatter#ISO_INSTANT} under the hood) —
 * so a client decodes the IDENTICAL string whether it reads the JSON text
 * frame or the Protobuf binary frame, per
 * {@code contracts/handling-event.proto}'s header comment.
 */
final class HandlingEventProtoMapper {

    private static final String ENUM_PREFIX = "HANDLING_EVENT_TYPE_";

    private HandlingEventProtoMapper() {
    }

    /** Builds the Protobuf wire form of {@code event}, ready for {@code toByteArray()}. */
    static HandlingEventOuterClass.HandlingEvent toProto(HandlingEvent event) {
        HandlingEventOuterClass.HandlingEvent.Builder builder = HandlingEventOuterClass.HandlingEvent.newBuilder()
                .setEventId(event.eventId())
                .setBookingId(event.bookingId())
                .setCargoId(event.cargoId())
                .setEventType(toProtoEventType(event.eventType()))
                .setLocation(event.location())
                .setOccurredAt(event.occurredAt().toString())
                .setRegisteredAt(event.registeredAt().toString());
        if (event.voyageNumber() != null) {
            builder.setVoyageNumber(event.voyageNumber());
        }
        if (event.amount() != null) {
            builder.setAmount(event.amount());
        }
        return builder.build();
    }

    /** The inverse of {@link #toProto}, used by the round-trip test to prove no information is lost. */
    static HandlingEvent fromProto(HandlingEventOuterClass.HandlingEvent proto) {
        return new HandlingEvent(
                proto.getEventId(),
                proto.getBookingId(),
                proto.getCargoId(),
                fromProtoEventType(proto.getEventType()),
                proto.getLocation(),
                java.time.Instant.parse(proto.getOccurredAt()),
                java.time.Instant.parse(proto.getRegisteredAt()),
                proto.hasVoyageNumber() ? proto.getVoyageNumber() : null,
                proto.hasAmount() ? proto.getAmount() : null);
    }

    /**
     * {@link HandlingEventType#HANDLING_EVENT_TYPE_UNSPECIFIED} is the one
     * member that is ALREADY fully prefixed on the Java side (it is never
     * actually sent by the server, but both enums still declare it, at
     * ordinal 0) — every other member is bare ({@code RECEIVE}, not
     * {@code HANDLING_EVENT_TYPE_RECEIVE}). Mirrors
     * {@code scripts/check-proto-parity.py}'s {@code pascal_to_upper_snake}/
     * prefix-stripping special case for the exact same reason.
     */
    private static HandlingEventOuterClass.HandlingEventType toProtoEventType(HandlingEventType type) {
        if (type == HandlingEventType.HANDLING_EVENT_TYPE_UNSPECIFIED) {
            return HandlingEventOuterClass.HandlingEventType.HANDLING_EVENT_TYPE_UNSPECIFIED;
        }
        return HandlingEventOuterClass.HandlingEventType.valueOf(ENUM_PREFIX + type.name());
    }

    private static HandlingEventType fromProtoEventType(HandlingEventOuterClass.HandlingEventType protoType) {
        if (protoType == HandlingEventOuterClass.HandlingEventType.HANDLING_EVENT_TYPE_UNSPECIFIED) {
            return HandlingEventType.HANDLING_EVENT_TYPE_UNSPECIFIED;
        }
        String name = protoType.name();
        if (!name.startsWith(ENUM_PREFIX)) {
            throw new IllegalArgumentException("Unexpected proto enum member outside the " + ENUM_PREFIX + " family: " + name);
        }
        return HandlingEventType.valueOf(name.substring(ENUM_PREFIX.length()));
    }
}
