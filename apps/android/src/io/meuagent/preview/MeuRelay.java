package io.meuagent.preview;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONException;
import org.json.JSONObject;

final class MeuRelay {
    private static final int MAX_PACKET = 512 * 1024;
    private final URI endpoint;
    private final SecretKeySpec requestKey;
    private final SecretKeySpec responseKey;
    private final SecureRandom random = new SecureRandom();

    MeuRelay(URI endpoint, byte[] secret) throws IOException {
        this.endpoint = endpoint;
        try {
            requestKey = derive("meu request v1", secret);
            responseKey = derive("meu response v1", secret);
        } catch (GeneralSecurityException error) {
            throw new IOException("Meu relay encryption unavailable", error);
        }
    }

    private static SecretKeySpec derive(String label, byte[] secret) throws GeneralSecurityException {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        digest.update(label.getBytes(StandardCharsets.US_ASCII));
        return new SecretKeySpec(digest.digest(secret), "AES");
    }

    JSONObject request(String path, JSONObject body, String requestId, String credential)
            throws IOException, JSONException {
        JSONObject message = new JSONObject()
                .put("path", "/" + path)
                .put("method", body == null ? "GET" : "POST")
                .put("at", System.currentTimeMillis() / 1000)
                .put("body", body).put("id", requestId).put("key", credential);
        byte[] nonce = new byte[12];
        random.nextBytes(nonce);
        try {
            byte[] encrypted = cipher(Cipher.ENCRYPT_MODE, requestKey, nonce)
                    .doFinal(message.toString().getBytes(StandardCharsets.UTF_8));
            byte[] reply = exchange(nonce, encrypted);
            if (reply.length < 28) throw new IOException("Invalid Meu relay response");
            Cipher decrypt = cipher(Cipher.DECRYPT_MODE, responseKey, Arrays.copyOf(reply, 12));
            decrypt.updateAAD(nonce);
            JSONObject decoded = new JSONObject(new String(
                    decrypt.doFinal(reply, 12, reply.length - 12), StandardCharsets.UTF_8));
            int status = decoded.getInt("status");
            if (status < 200 || status >= 300) throw new MeuClient.HttpError(status);
            return decoded.getJSONObject("body");
        } catch (GeneralSecurityException error) {
            throw new IOException("Could not verify the Meu relay response", error);
        }
    }

    private static Cipher cipher(int mode, SecretKeySpec key, byte[] nonce) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(mode, key, new GCMParameterSpec(128, nonce));
        return cipher;
    }

    private byte[] exchange(byte[] nonce, byte[] encrypted) throws IOException {
        HttpsURLConnection connection = (HttpsURLConnection) endpoint.toURL().openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(15000);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Content-Type", "application/octet-stream");
            connection.setDoOutput(true);
            connection.setFixedLengthStreamingMode(nonce.length + encrypted.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(nonce);
                output.write(encrypted);
            }
            if (connection.getResponseCode() != 200) throw new IOException("Meu relay unavailable");
            try (InputStream input = connection.getInputStream();
                 ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                for (int count; (count = input.read(buffer)) != -1; ) {
                    if (output.size() + count > MAX_PACKET) throw new IOException("Relay response too large");
                    output.write(buffer, 0, count);
                }
                return output.toByteArray();
            }
        } finally {
            connection.disconnect();
        }
    }
}
