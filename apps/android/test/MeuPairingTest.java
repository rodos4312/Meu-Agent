package io.meuagent.preview;

import java.io.InputStream;
import java.net.InetAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.Base64;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLHandshakeException;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLServerSocket;
import javax.net.ssl.SSLSocket;

public final class MeuPairingTest {
    private static final String KEY = "test-only-credential-0123456789abcdef";
    private static final char[] PASSWORD = "android".toCharArray();

    public static void main(String[] args) throws Exception {
        KeyStore paired = load(args[0]);
        KeyStore other = load(args[1]);
        MeuPairing pairing = MeuPairing.parse(code("https://127.0.0.1", paired));
        if (!KEY.equals(pairing.key) || !"https://127.0.0.1/".equals(pairing.endpoint.toString())) {
            throw new AssertionError("Pairing did not preserve the HTTPS origin and key");
        }
        reject(code("http://127.0.0.1", paired));
        reject("meu1.invalid");
        reject("meu1." + encode("https://127.0.0.1") + "." + encode("short") + ".bad");
        handshake(pairing, paired, "127.0.0.1", true);
        handshake(pairing, other, "127.0.0.1", false);
        handshake(pairing, paired, "wrong.example", false);
        String relay = "https://relay.example/v1/" + String.join("", java.util.Collections.nCopies(64, "0"))
                + "/exchange";
        String code = "meu3." + encode(relay) + "." + encode(KEY) + "."
                + Base64.getUrlEncoder().withoutPadding().encodeToString(new byte[32]);
        MeuPairing remote = MeuPairing.parse(code);
        String deviceKey = KEY + "-device";
        MeuPairing saved = MeuPairing.parseSaved(remote.rememberedCode(deviceKey));
        if (!remote.oneTime || saved.oneTime || !deviceKey.equals(saved.key)
                || !remote.endpoint.equals(saved.endpoint) || !java.util.Arrays.equals(remote.relaySecret, saved.relaySecret)) {
            throw new AssertionError("Restoring a relay pairing must reuse its identity and replace the one-time challenge");
        }
        reject(remote.rememberedCode(deviceKey));
        reject(code.replace(encode(relay), encode("https:broken")));
        reject(code.replace(encode(relay), encode(relay + "?extra=1")));
        System.out.println("Meu Android pairing accepts the matching TLS identity and rejects mismatches.");
    }

    private static KeyStore load(String filename) throws Exception {
        KeyStore keys = KeyStore.getInstance("PKCS12");
        try (InputStream input = Files.newInputStream(Paths.get(filename))) {
            keys.load(input, PASSWORD);
        }
        return keys;
    }

    private static String encode(String value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value.getBytes(StandardCharsets.US_ASCII));
    }

    private static String code(String origin, KeyStore keys) throws Exception {
        String certificate = Base64.getUrlEncoder().withoutPadding()
                .encodeToString(keys.getCertificate("gateway").getEncoded());
        return "meu1." + encode(origin) + "." + encode(KEY) + "." + certificate;
    }

    private static void reject(String code) throws Exception {
        try {
            MeuPairing.parse(code);
            throw new AssertionError("Invalid pairing code was accepted");
        } catch (GeneralSecurityException | IllegalArgumentException expected) {
            // The app refuses a malformed code before starting the connection.
        }
    }

    private static void handshake(MeuPairing pairing, KeyStore keys, String hostname, boolean accepted)
            throws Exception {
        KeyManagerFactory managers = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        managers.init(keys, PASSWORD);
        SSLContext serverTls = SSLContext.getInstance("TLS");
        serverTls.init(managers.getKeyManagers(), null, null);
        InetAddress loopback = InetAddress.getByName("127.0.0.1");
        try (SSLServerSocket server = (SSLServerSocket)
                serverTls.getServerSocketFactory().createServerSocket(0, 1, loopback)) {
            server.setSoTimeout(5000);
            FutureTask<Boolean> remote = new FutureTask<>(() -> {
                try (SSLSocket socket = (SSLSocket) server.accept()) {
                    socket.setSoTimeout(5000);
                    socket.startHandshake();
                    return true;
                } catch (SSLHandshakeException error) {
                    return false;
                }
            });
            Thread thread = new Thread(remote);
            thread.setDaemon(true);
            thread.start();
            try (Socket transport = new Socket(loopback, server.getLocalPort());
                 SSLSocket client = (SSLSocket) pairing.sockets.createSocket(
                         transport, hostname, server.getLocalPort(), true)) {
                client.setSoTimeout(5000);
                SSLParameters parameters = client.getSSLParameters();
                parameters.setEndpointIdentificationAlgorithm("HTTPS");
                client.setSSLParameters(parameters);
                client.startHandshake();
                if (!accepted) throw new AssertionError("Incorrect TLS identity was accepted");
            } catch (SSLHandshakeException error) {
                if (accepted) throw error;
            }
            if (accepted && !remote.get(5, TimeUnit.SECONDS)) {
                throw new AssertionError("Server did not complete the expected handshake");
            }
        }
    }
}
