package com.patterncatalyst.shipping.backplane;

import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;

/**
 * Minimal query-string parser — forked verbatim from
 * {@code examples/part4-connection/quarkus}'s class of the same name.
 * WebSockets Next does not parse query parameters for the caller; this pulls
 * the {@code afterEventId} query parameter (see PROTOCOL.md) out of
 * {@code WebSocketConnection#handshakeRequest().query()}, which returns the
 * raw, un-split query string.
 */
final class QueryParams {

    private QueryParams() {
    }

    static String get(String rawQuery, String name) {
        if (rawQuery == null || rawQuery.isEmpty()) {
            return null;
        }
        for (String pair : rawQuery.split("&")) {
            if (pair.isEmpty()) {
                continue;
            }
            int eq = pair.indexOf('=');
            String key = eq >= 0 ? pair.substring(0, eq) : pair;
            String rawValue = eq >= 0 ? pair.substring(eq + 1) : "";
            if (URLDecoder.decode(key, StandardCharsets.UTF_8).equals(name)) {
                return URLDecoder.decode(rawValue, StandardCharsets.UTF_8);
            }
        }
        return null;
    }
}
