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

    private MeuPairing(URI endpoint, String key, SSLSocketFactory sockets, boolean oneTime) {
        this.endpoint = endpoint;
        this.key = key;
        this.sockets = sockets;
        this.oneTime = oneTime;
    }

    static MeuPairing parse(String input) throws GeneralSecurityException {
        String code = input.trim();
        if (code.length() > 8192) throw new IllegalArgumentException("Pairing code is too long");
        String[] parts = code.split("\\.", -1);
        if (parts.length != 4 || !("meu1".equals(parts[0]) || "meu2".equals(parts[0]))) {
            throw new IllegalArgumentException("Expected a Meu pairing code");
        }
        Base64.Decoder decoder = Base64.getUrlDecoder();
        URI endpoint = MeuEndpoint.parse(new String(decoder.decode(parts[1]), StandardCharsets.US_ASCII));
        String key = new String(decoder.decode(parts[2]), StandardCharsets.US_ASCII);
        if (!key.matches("[!-~]{32,512}")) throw new IllegalArgumentException("Invalid pairing key");
        byte[] der = decoder.decode(parts[3]);
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
        return new MeuPairing(endpoint, key, tls.getSocketFactory(), "meu2".equals(parts[0]));
    }
}
