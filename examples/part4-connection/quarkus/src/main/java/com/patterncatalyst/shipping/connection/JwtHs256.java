package com.patterncatalyst.shipping.connection;

import com.fasterxml.jackson.databind.ObjectMapper;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Ch17 example — a minimal, dependency-free HS256 JWT mint/verify pair.
 *
 * <p>Deliberately NOT {@code quarkus-smallrye-jwt}: that extension is built
 * around RS256/JWKS (asymmetric keys, a key-rotation endpoint) — the right
 * shape for a multi-service-audience token, but overkill for this chapter's
 * single shared-secret HS256 token (mirrors the Python sibling's choice of
 * plain PyJWT over a heavier OIDC client for the same reason). {@code
 * javax.crypto} (HMAC-SHA256) and Jackson (already pulled in transitively by
 * {@code quarkus-websockets-next}, see {@code HandlingEvent}) are the only
 * two things this needs — no new dependency to pin.
 *
 * <p>The secret comes from {@code ws.jwt.secret}
 * ({@code application.properties} maps it from the {@code WS_JWT_SECRET}
 * env var, dev default {@code dev-secret-change-me}) — see
 * {@link com.patterncatalyst.shipping.connection.HandlingEventConnectionWebSocket}.
 */
public final class JwtHs256 {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Base64.Encoder URL_ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder URL_DECODER = Base64.getUrlDecoder();
    private static final String HEADER_JSON = "{\"alg\":\"HS256\",\"typ\":\"JWT\"}";
    private static final String HMAC_ALGORITHM = "HmacSHA256";

    private JwtHs256() {
    }

    /**
     * The result of {@link #verify(String, String)}: either {@code valid}
     * with the token's {@code sub} claim, or rejected with a {@code reason}
     * — logged server-side only (see {@code HandlingEventConnectionWebSocket}),
     * never echoed back to the client on the wire, so a prober can't use it
     * as a signature oracle (same convention as the Python sibling's
     * {@code AuthError}).
     */
    public record VerificationResult(boolean valid, String subject, String reason) {
        public static VerificationResult ok(String subject) {
            return new VerificationResult(true, subject, null);
        }

        public static VerificationResult rejected(String reason) {
            return new VerificationResult(false, null, reason);
        }
    }

    /**
     * Mints a compact HS256 JWT ({@code header.payload.signature}, each
     * segment base64url-encoded without padding) carrying {@code sub},
     * {@code bookingId}, {@code iat}, and {@code exp} claims.
     */
    public static String mint(String subject, String bookingId, Instant issuedAt, Instant expiresAt, String secret) {
        try {
            Map<String, Object> claims = new LinkedHashMap<>();
            claims.put("sub", subject);
            claims.put("bookingId", bookingId);
            claims.put("iat", issuedAt.getEpochSecond());
            claims.put("exp", expiresAt.getEpochSecond());

            String headerB64 = URL_ENCODER.encodeToString(HEADER_JSON.getBytes(StandardCharsets.UTF_8));
            String payloadB64 = URL_ENCODER.encodeToString(MAPPER.writeValueAsBytes(claims));
            String signingInput = headerB64 + "." + payloadB64;
            String signatureB64 = URL_ENCODER.encodeToString(hmac(signingInput, secret));
            return signingInput + "." + signatureB64;
        } catch (Exception e) {
            throw new IllegalStateException("failed to mint token", e);
        }
    }

    /**
     * Verifies a compact HS256 JWT's structure, signature (constant-time
     * comparison via {@link MessageDigest#isEqual}), and expiry against
     * {@code secret}. Never throws — every failure mode (missing, malformed,
     * bad signature, expired) comes back as a rejected {@link VerificationResult}.
     */
    public static VerificationResult verify(String token, String secret) {
        if (token == null || token.isBlank()) {
            return VerificationResult.rejected("missing token");
        }
        String[] parts = token.split("\\.", -1);
        if (parts.length != 3) {
            return VerificationResult.rejected("malformed token (expected 3 segments, got " + parts.length + ")");
        }
        try {
            String signingInput = parts[0] + "." + parts[1];
            byte[] expectedSignature = hmac(signingInput, secret);
            byte[] actualSignature = URL_DECODER.decode(parts[2]);
            if (!MessageDigest.isEqual(expectedSignature, actualSignature)) {
                return VerificationResult.rejected("bad signature");
            }

            Map<?, ?> claims = MAPPER.readValue(URL_DECODER.decode(parts[1]), Map.class);
            Object expClaim = claims.get("exp");
            if (!(expClaim instanceof Number expNumber)) {
                return VerificationResult.rejected("missing or invalid exp claim");
            }
            if (Instant.now().getEpochSecond() >= expNumber.longValue()) {
                return VerificationResult.rejected("expired");
            }

            Object sub = claims.get("sub");
            return VerificationResult.ok(sub == null ? null : sub.toString());
        } catch (Exception e) {
            return VerificationResult.rejected("malformed token: " + e.getMessage());
        }
    }

    private static byte[] hmac(String data, String secret) throws Exception {
        Mac mac = Mac.getInstance(HMAC_ALGORITHM);
        mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), HMAC_ALGORITHM));
        return mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
    }
}
