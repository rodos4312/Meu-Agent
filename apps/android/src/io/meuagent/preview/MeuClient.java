package io.meuagent.preview;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLSocketFactory;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class MeuClient {
    private final URI endpoint;
    private final String credential;
    private final SSLSocketFactory sockets;
    private boolean mobileSessions;

    MeuClient(URI endpoint, String credential) {
        this(endpoint, credential, null);
    }

    MeuClient(URI endpoint, String credential, SSLSocketFactory sockets) {
        this.endpoint = endpoint;
        this.credential = credential;
        this.sockets = sockets;
    }

    boolean usesPairing() {
        return sockets != null;
    }

    boolean supportsSessions() {
        return mobileSessions;
    }

    void verify() throws IOException, JSONException {
        verify(false);
    }

    private void verify(boolean paired) throws IOException, JSONException {
        JSONObject capabilities = request("v1/capabilities", null, null);
        JSONObject features = capabilities.getJSONObject("features");
        JSONObject replay = features.getJSONObject("runs_idempotency");
        if (!capabilities.getJSONObject("auth").optBoolean("required")
                || !features.optBoolean("run_submission") || !features.optBoolean("run_status")
                || (!replay.optBoolean("durable") && !(paired && replay.optBoolean("pairing_session")))
                || replay.optInt("retention_seconds") < 3600) {
            throw new IOException("Unsupported gateway");
        }
        mobileSessions = paired && features.optBoolean("mobile_sessions");
    }

    static MeuClient pair(MeuPairing pairing) throws IOException, JSONException {
        if (!pairing.oneTime) {
            MeuClient client = new MeuClient(pairing.endpoint, pairing.key, pairing.sockets);
            client.verify();
            return client;
        }
        MeuClient bootstrap = new MeuClient(pairing.endpoint, null, pairing.sockets);
        String key = bootstrap.request("meu/pair", new JSONObject().put("challenge", pairing.key), null)
                .getString("key");
        if (!key.matches("[A-Za-z0-9_-]{32,128}")) throw new IOException("Invalid device key");
        MeuClient client = new MeuClient(pairing.endpoint, key, pairing.sockets);
        client.verify(true);
        return client;
    }

    String submit(String session, String input, String requestId) throws IOException, JSONException {
        JSONObject body = new JSONObject().put("session_id", session).put("input", input);
        String runId = request("v1/runs", body, requestId).getString("run_id");
        if (!runId.matches("run_[a-zA-Z0-9_-]{1,128}")) throw new IOException("Invalid run ID");
        return runId;
    }

    JSONArray sessions() throws IOException, JSONException {
        return request("meu/sessions", null, null).getJSONArray("sessions");
    }

    JSONObject createSession(String requestId) throws IOException, JSONException {
        return request("meu/sessions", new JSONObject(), requestId);
    }

    JSONObject openSession(String sessionId) throws IOException, JSONException {
        return openSession(sessionId, "");
    }

    JSONObject openSession(String sessionId, String revision) throws IOException, JSONException {
        if (!sessionId.matches("local-[a-f0-9]{64}")) throw new IOException("Invalid session ID");
        String query = revision.matches("[0-9a-f]{64}") ? "?since=" + revision : "";
        return request("meu/sessions/" + sessionId + query, null, null);
    }

    JSONObject status(String runId) throws IOException, JSONException {
        JSONObject run = request("v1/runs/" + runId, null, null);
        if (!runId.equals(run.optString("run_id"))) throw new IOException("Run ID mismatch");
        return run;
    }

    private JSONObject request(String path, JSONObject body, String requestId)
            throws IOException, JSONException {
        HttpsURLConnection connection = (HttpsURLConnection) endpoint.resolve(path).toURL().openConnection();
        try {
            if (sockets != null) connection.setSSLSocketFactory(sockets);
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(15000);
            if (credential != null) connection.setRequestProperty("Authorization", "Bearer " + credential);
            connection.setRequestProperty("Accept", "application/json");
            if (body != null) {
                byte[] data = body.toString().getBytes(StandardCharsets.UTF_8);
                connection.setRequestMethod("POST");
                if (requestId != null) connection.setRequestProperty("Idempotency-Key", requestId);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(data.length);
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(data);
                }
            }
            int status = connection.getResponseCode();
            if (status < 200 || status >= 300) throw new HttpError(status);
            return readJson(connection);
        } finally {
            connection.disconnect();
        }
    }

    private static JSONObject readJson(HttpsURLConnection connection) throws IOException, JSONException {
        try (InputStream input = connection.getInputStream();
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            for (int count; (count = input.read(buffer)) != -1; ) {
                if (output.size() + count > 1024 * 1024) throw new IOException("Response too large");
                output.write(buffer, 0, count);
            }
            return new JSONObject(output.toString("UTF-8"));
        }
    }

    static final class HttpError extends IOException {
        final int status;

        HttpError(int status) {
            super("Gateway HTTP " + status);
            this.status = status;
        }
    }
}
