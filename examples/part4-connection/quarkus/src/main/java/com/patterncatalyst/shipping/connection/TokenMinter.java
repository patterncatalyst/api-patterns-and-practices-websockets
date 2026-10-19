package com.patterncatalyst.shipping.connection;

import java.time.Duration;
import java.time.Instant;

/**
 * Ch17 example — mint a JWT for exercising the auth-gated handling-events
 * feed locally, without standing up a real identity provider. Mirrors the
 * Python sibling's {@code app/mint_token.py} one-for-one (same default
 * booking id, same three modes).
 *
 * <pre>
 *   ./mvnw -q compile
 *   java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter valid
 *   java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter expired
 *   java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter bad-sig
 * </pre>
 *
 * <p>Prints the compact JWT to stdout and nothing else, so it composes
 * directly into a shell variable or a WebSocket URL:
 *
 * <pre>
 *   TOKEN="$(java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter valid)"
 *   websocat "ws://localhost:8080/ws/v1/bookings/bkg_.../handling-events?token=$TOKEN"
 * </pre>
 *
 * <ul>
 *   <li>{@code valid} — signed with {@code WS_JWT_SECRET} (dev default
 *       {@code dev-secret-change-me}), {@code exp} 15 minutes out.</li>
 *   <li>{@code expired} — signed with the same secret, {@code exp} already
 *       15 minutes in the past.</li>
 *   <li>{@code bad-sig} — signed with a DIFFERENT secret, so
 *       {@link JwtHs256#verify} against the real {@code WS_JWT_SECRET}
 *       fails on signature comparison, not on structure or expiry.</li>
 * </ul>
 */
public final class TokenMinter {

    private static final String DEFAULT_SECRET = "dev-secret-change-me";
    private static final String DEFAULT_SUBJECT = "test-client";
    private static final String DEFAULT_BOOKING_ID = "bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A";

    private TokenMinter() {
    }

    public static void main(String[] args) {
        if (args.length < 1) {
            System.err.println("usage: TokenMinter <valid|expired|bad-sig> [bookingId] [secret]");
            System.exit(2);
            return;
        }
        String kind = args[0];
        String bookingId = args.length > 1 ? args[1] : DEFAULT_BOOKING_ID;
        String secret = args.length > 2 ? args[2] : System.getenv().getOrDefault("WS_JWT_SECRET", DEFAULT_SECRET);

        String token = switch (kind) {
            case "valid" -> mintValid(bookingId, secret);
            case "expired" -> mintExpired(bookingId, secret);
            case "bad-sig" -> mintBadSignature(bookingId, secret);
            default -> {
                System.err.println("unknown token kind: " + kind + " (expected valid|expired|bad-sig)");
                System.exit(2);
                yield null;
            }
        };
        if (token != null) {
            System.out.println(token);
        }
    }

    public static String mintValid(String bookingId, String secret) {
        Instant now = Instant.now();
        return JwtHs256.mint(DEFAULT_SUBJECT, bookingId, now, now.plus(Duration.ofMinutes(15)), secret);
    }

    public static String mintExpired(String bookingId, String secret) {
        Instant now = Instant.now();
        return JwtHs256.mint(DEFAULT_SUBJECT, bookingId, now.minus(Duration.ofMinutes(30)),
                now.minus(Duration.ofMinutes(15)), secret);
    }

    public static String mintBadSignature(String bookingId, String secret) {
        // Signed with a DIFFERENT secret than the server validates against,
        // so JwtHs256.verify() against the real secret fails on signature
        // comparison, not on structure or expiry.
        return mintValid(bookingId, secret + "-wrong");
    }
}
