package com.patterncatalyst.shipping.handlingevents;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.time.Instant;

/**
 * A single handling event recorded against a booking's cargo — mirrors
 * {@code components.schemas.HandlingEvent} in {@code contracts/asyncapi.yaml}
 * field-for-field. Byte-for-byte fork of part3/part4's record — Part 6 is
 * about observability, not new message content. Jackson (pulled in
 * transitively by {@code quarkus-websockets-next}) serializes this record to
 * the JSON text frame pushed over the WebSocket; {@code @JsonInclude(NON_NULL)}
 * omits {@code voyageNumber}/{@code amount} entirely when absent, matching
 * the contract (they are not in {@code required}).
 *
 * <p>{@code location} (a UN/LOCODE, e.g. {@code USNYC}) and {@code amount}
 * (a decimal string, e.g. {@code "125.00"}, never a float) are modeled as
 * plain {@link String}s because the contract defines both as
 * {@code type: string} with a {@code pattern} — not as nested objects.
 *
 * @param eventId      unique identifier for this event ({@code evt_}-prefixed ULID)
 * @param bookingId    the booking this event belongs to ({@code bkg_}-prefixed ULID)
 * @param cargoId      the cargo this event was recorded against ({@code crg_}-prefixed ULID)
 * @param eventType    the kind of handling event
 * @param location     UN/LOCODE of the port or terminal
 * @param occurredAt   when the event physically happened
 * @param registeredAt when the event was recorded by the system (&gt;= occurredAt)
 * @param voyageNumber optional carrier voyage number (LOAD/UNLOAD events)
 * @param amount       optional decimal-string amount (e.g. CUSTOMS events)
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HandlingEvent(
        String eventId,
        String bookingId,
        String cargoId,
        HandlingEventType eventType,
        String location,
        Instant occurredAt,
        Instant registeredAt,
        String voyageNumber,
        String amount) {
}
