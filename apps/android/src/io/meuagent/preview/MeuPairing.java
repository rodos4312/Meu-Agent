package io.meuagent.preview;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.Base64;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManagerFactory;

final class MeuPairing {
    final URI endpoint;
    final String key;
    final SSLSocketFactory sockets;
    final boolean oneTime;
    final byte[] relaySecret;
    private final String encodedCertificate;

    private MeuPairing(URI endpoint, String key, SSLSocketFactory sockets, boolean oneTime,
                       String encodedCertificate, byte[] relaySecret) {
        this.endpoint = endpoint;
        this.key = key;
        this.sockets = sockets;
        this.oneTime = oneTime;
        this.encodedCertificate = encodedCertificate;
        this.relaySecret = relaySecret;
    }

    String rememberedCode(String deviceKey) {
        Base64.Encoder encoder = Base64.getUrlEncoder().withoutPadding();
        String version = relaySecret == null ? "meu1." : "meu4.";
        return version + encoder.encodeToString(endpoint.toString().getBytes(StandardCharsets.US_ASCII))
                + "." + encoder.encodeToString(deviceKey.getBytes(StandardCharsets.US_ASCII))
                + "." + encodedCertificate;
    }

    static MeuPairing parse(String input) throws GeneralSecurityException {
        return parse(input, false);
    }

    static MeuPairing parseSaved(String input) throws GeneralSecurityException {
        return parse(input, true);
    }

    private static MeuPairing parse(String input, boolean saved) throws GeneralSecurityException {
        String code = input.trim();
        if (code.length() > 8192) throw new IllegalArgumentException("Pairing code is too long");
        String[] parts = code.split("\\.", -1);
        if (parts.length != 4 || !(saved ? "meu1".equals(parts[0]) || "meu4".equals(parts[0])
                : "meu1".equals(parts[0]) || "meu2".equals(parts[0]) || "meu3".equals(parts[0]))) {
            throw new IllegalArgumentException("Expected a Meu pairing code");
        }
        Base64.Decoder decoder = Base64.getUrlDecoder();
        String address = new String(decoder.decode(parts[1]), StandardCharsets.US_ASCII);
        String key = new String(decoder.decode(parts[2]), StandardCharsets.US_ASCII);
        if (!key.matches("[!-~]{32,512}")) throw new IllegalArgumentException("Invalid pairing key");
        byte[] der = decoder.decode(parts[3]);
        if ("meu3".equals(parts[0]) || "meu4".equals(parts[0])) {
            URI relay = URI.create(address);
            if (!"https".equals(relay.getScheme()) || relay.getHost() == null || relay.getRawUserInfo() != null
                    || relay.getPort() == 0 || relay.getPort() > 65535
                    || relay.getRawQuery() != null || relay.getRawFragment() != null
                    || !relay.getRawPath().matches("/v1/[0-9a-f]{64}/exchange") || der.length != 32) {
                throw new IllegalArgumentException("Invalid Meu relay");
            }
            return new MeuPairing(relay, key, null, !saved, parts[3], der);
        }
        URI endpoint = MeuEndpoint.parse(address);
        ByteArrayInputStream certificateData = new ByteArrayInputStream(der);
        X509Certificate certificate = (X509Certificate) CertificateFactory.getInstance("X.509")
                .generateCertificate(certificateData);
        if (certificateData.available() != 0 || certificate.getBasicConstraints() >= 0) {
            throw new IllegalArgumentException("Expected a single gateway certificate");
        }
        certificate.checkValidity();
        KeyStore store = KeyStore.getInstance(KeyStore.getDefaultType());
        try {
            store.load(null, null);
        } catch (IOException error) {
            throw new GeneralSecurityException(error);
        }
        store.setCertificateEntry("meu-gateway", certificate);
        TrustManagerFactory trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        trust.init(store);
        SSLContext tls = SSLContext.getInstance("TLS");
        tls.init(null, trust.getTrustManagers(), null);
        return new MeuPairing(endpoint, key, tls.getSocketFactory(), "meu2".equals(parts[0]), parts[3], null);
    }
}
