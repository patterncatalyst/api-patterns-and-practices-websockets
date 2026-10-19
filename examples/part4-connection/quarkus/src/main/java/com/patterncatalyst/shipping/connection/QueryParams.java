package com.patterncatalyst.shipping.connection;

import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;

/**
 * Minimal query-string parser. WebSockets Next does not parse query
 * parameters for the caller — the reference guide's "Path parameters"
 * section notes query params are not supported as {@code @PathParam}-style
 * injected values and points instead at
 * {@code WebSocketConnection#handshakeRequest().query()}, which returns the
 * raw, un-split query string. {@link HandlingEventConnectionWebSocket} uses
 * this to pull the Ch17 {@code token} query parameter out of it.
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
