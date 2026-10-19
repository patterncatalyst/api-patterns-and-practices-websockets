package com.patterncatalyst.shipping.handlingevents;

/**
 * The kind of handling event — mirrors {@code components.schemas.HandlingEventType}
 * in {@code contracts/asyncapi.yaml}. Byte-for-byte fork of part3/part4's
 * enum. Enum constant names ARE the contract's SCREAMING_SNAKE wire values;
 * Jackson serializes an enum as {@link #name()} by default, so no extra
 * annotation is needed to keep this in sync.
 *
 * <p>{@link #HANDLING_EVENT_TYPE_UNSPECIFIED} is the zero value and is never
 * sent by the server — it exists only so deserialization has a safe default,
 * matching the {@code *_UNSPECIFIED}-zero-value convention used across the
 * series' gRPC enums.
 */
public enum HandlingEventType {
    HANDLING_EVENT_TYPE_UNSPECIFIED,
    RECEIVE,
    LOAD,
    UNLOAD,
    CUSTOMS,
    CLAIM,
    HOLD,
    DELIVERED
}
