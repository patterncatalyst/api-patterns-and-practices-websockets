package com.patterncatalyst.shipping.connection;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Ch13 example — the in-band JSON error frame sent to the client BEFORE the
 * connection is closed with {@link CloseCodes#BAD_REQUEST}:
 * {@code {"error":{"code":"BAD_REQUEST","message":"..."}}}. Identical shape
 * to the Python sibling's {@code _error_envelope} (see
 * {@code examples/part4-connection/python/app/ws_server.py}) so a client
 * parses the same JSON regardless of which stack it talks to.
 *
 * <p>{@code BAD_REQUEST} is the only {@code code} this channel emits: every
 * client-sent frame is invalid here, since the contract
 * ({@code operations.receiveHandlingEvent}) defines no client-to-server
 * operation at all. A channel with multiple distinct failure modes would
 * add more {@code code} values.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ErrorEnvelope(ErrorBody error) {

    public record ErrorBody(String code, String message) {
    }

    public static ErrorEnvelope badRequest(String message) {
        return new ErrorEnvelope(new ErrorBody("BAD_REQUEST", message));
    }
}
