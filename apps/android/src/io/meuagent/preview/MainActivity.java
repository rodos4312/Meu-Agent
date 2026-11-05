package io.meuagent.preview;

import android.app.Activity;
import android.Manifest;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.SystemClock;
import android.text.InputFilter;
import android.text.InputType;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.IOException;
import java.security.GeneralSecurityException;
import java.text.DateFormat;
import java.util.Date;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final int INK = 0xff15192b;
    private static final int MUTED = 0xff50576f;
    private static final int ACCENT = 0xff4541bb;
    private static final long RETRY_WINDOW_MS = 60 * 60 * 1000;
    private static final int CAMERA_REQUEST = 4;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private LinearLayout root;
    private TextView status;
    private MeuClient client;
    private String sessionId;
    private String newSessionRequest;
    private Pending pending;
    private MeuQrScanner scanner;

    private static final class Pending {
        final String requestId = UUID.randomUUID().toString();
        final long createdAt = SystemClock.elapsedRealtime();
        final String input;
        String runId;

        Pending(String input) { this.input = input; }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE);
        showConnection();
    }

    @Override protected void onDestroy() {
        worker.shutdownNow();
        super.onDestroy();
    }

    @Override protected void onPause() {
        if (scanner != null) scanner.stop();
        super.onPause();
    }

    @Override protected void onResume() {
        super.onResume();
        if (scanner != null) scanner.start();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private TextView label(String value, int size, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setPadding(0, dp(8), 0, dp(8));
        return view;
    }

    private Button button(String caption) {
        Button view = new Button(this);
        view.setAllCaps(false);
        view.setText(caption);
        view.setTextColor(ACCENT);
        return view;
    }

    private EditText field(String hint, int type, int maxLength) {
        EditText view = new EditText(this);
        view.setHint(hint);
        view.setInputType(type);
        view.setFilters(new InputFilter[] {new InputFilter.LengthFilter(maxLength)});
        view.setSaveEnabled(false);
        view.setTextColor(INK);
        return view;
    }

    private void screen(String subtitle) {
        if (scanner != null) {
            scanner.stop();
            scanner = null;
        }
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setFocusableInTouchMode(true);
        root.setBackgroundColor(0xfff7f8ff);
        root.setPadding(dp(24), dp(12), dp(24), dp(12));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets edge = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                view.setPadding(dp(24) + edge.left, dp(12) + edge.top,
                        dp(24) + edge.right, dp(12) + edge.bottom);
            }
            return insets;
        });
        TextView title = label("Meu", 34, INK);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        root.addView(title);
        root.addView(label(subtitle, 16, MUTED));
        setContentView(root);
        root.requestFocus();
    }

    private void showConnection() {
        client = null;
        pending = null;
        newSessionRequest = null;
        showPairing(null, "");
    }

    private void showPairing(String scanned, String message) {
        screen("Pair with Meu on your computer");
        EditText code = field("Paste pairing code", InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD, 8192);
        code.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        Button scan = button("Scan pairing code");
        Button pair = button("Connect with pasted code");
        Button manual = button("Enter address manually");
        status = label(message.isEmpty() ? "On your computer, open Settings → Gateways → Connect a phone."
                : message, 14, MUTED);
        root.addView(scan);
        root.addView(code);
        root.addView(pair);
        root.addView(manual);
        root.addView(status);
        scan.setOnClickListener(view -> scanPairing());
        Runnable useCode = () -> {
            try {
                MeuPairing pairing = MeuPairing.parse(code.getText().toString());
                connect(() -> MeuClient.pair(pairing), true, code, pair, manual, scan);
            } catch (IllegalArgumentException | GeneralSecurityException error) {
                status.setText("The pairing code is invalid or has expired.");
            }
        };
        pair.setOnClickListener(view -> useCode.run());
        manual.setOnClickListener(view -> showManualConnection());
        if (scanned != null) {
            code.setText(scanned);
            useCode.run();
        }
    }

    private void scanPairing() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] {Manifest.permission.CAMERA}, CAMERA_REQUEST);
            return;
        }
        screen("Point the camera at the QR code in Meu on your computer.");
        scanner = new MeuQrScanner(this, worker, code -> showPairing(code, ""),
                () -> showPairing(null, "The rear camera is unavailable."));
        root.addView(scanner, new LinearLayout.LayoutParams(-1, 0, 1));
        Button cancel = button("Cancel scan");
        cancel.setOnClickListener(view -> showPairing(null, ""));
        root.addView(cancel);
        scanner.start();
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == CAMERA_REQUEST) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) scanPairing();
            else showPairing(null, "Allow camera access to scan the code, or paste it here.");
        }
    }

    private void showManualConnection() {
        screen("Connect to your Meu test gateway");
        EditText address = field("https://your-meu-gateway", InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_URI, 512);
        EditText key = field("Gateway access key", InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD, 512);
        key.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        Button connect = button("Connect");
        Button back = button("Use a pairing code");
        status = label("Use the HTTPS address of your test setup.", 14, MUTED);
        root.addView(address);
        root.addView(key);
        root.addView(connect);
        root.addView(back);
        root.addView(status);
        back.setOnClickListener(view -> showPairing(null, ""));
        connect.setOnClickListener(view -> {
            try {
                String credential = key.getText().toString().trim();
                if (!credential.matches("[!-~]{1,512}")) {
                    status.setText("Enter the test gateway access key.");
                    return;
                }
                MeuClient candidate = new MeuClient(MeuEndpoint.parse(address.getText().toString()), credential);
                connect(() -> {
                    candidate.verify();
                    return candidate;
                }, false, key, connect, back);
            } catch (IllegalArgumentException error) {
                status.setText("Enter an HTTPS address with a hostname and optional port.");
            }
        });
    }

    private interface ConnectionAttempt {
        MeuClient open() throws IOException, JSONException;
    }

    private void connect(ConnectionAttempt attempt, boolean pairing, EditText secret, Button... buttons) {
        for (Button button : buttons) button.setEnabled(false);
        status.setText("Checking the connection…");
        worker.execute(() -> {
            try {
                MeuClient candidate = attempt.open();
                onScreen(() -> {
                    secret.setText("");
                    client = candidate;
                    if (candidate.supportsSessions()) showSessions();
                    else {
                        sessionId = "meu-android-" + UUID.randomUUID();
                        showChat(null);
                    }
                });
            } catch (IOException | JSONException error) {
                onScreen(() -> {
                    for (Button button : buttons) button.setEnabled(true);
                    status.setText(pairing ? pairingErrorText(error) : errorText(error));
                });
            }
        });
    }

    private void showSessions() {
        pending = null;
        sessionId = null;
        screen("Sessions");
        LinearLayout page = root;
        MeuClient connected = client;
        Button create = button("New session");
        Button refresh = button("Refresh sessions");
        create.setEnabled(false);
        refresh.setEnabled(false);
        Button disconnect = button("Change connection");
        disconnect.setOnClickListener(view -> showConnection());
        ScrollView scroll = new ScrollView(this);
        LinearLayout entries = new LinearLayout(this);
        entries.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(entries);
        status = label("Loading sessions…", 14, MUTED);
        root.addView(create);
        root.addView(refresh);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        root.addView(status);
        root.addView(disconnect);

        create.setOnClickListener(view -> {
            if (newSessionRequest == null) newSessionRequest = UUID.randomUUID().toString();
            String requestId = newSessionRequest;
            loadSession(page, create, refresh, () -> connected.createSession(requestId), true);
        });
        refresh.setOnClickListener(view -> showSessions());
        worker.execute(() -> {
            try {
                JSONArray sessions = connected.sessions();
                onScreen(() -> {
                    if (root != page) return;
                    for (int index = 0; index < sessions.length(); index++) {
                        JSONObject item = sessions.optJSONObject(index);
                        if (item == null) continue;
                        String title = item.optString("title", "New session");
                        double started = item.optDouble("started_at", 0);
                        String date = started > 0 ? DateFormat.getDateTimeInstance(DateFormat.SHORT,
                                DateFormat.SHORT).format(new Date((long) (started * 1000))) : "";
                        Button open = button(date.isEmpty() ? title : title + "\n" + date);
                        open.setOnClickListener(view -> {
                            newSessionRequest = null;
                            loadSession(page, create, refresh,
                                    () -> connected.openSession(item.optString("id")), false);
                        });
                        entries.addView(open);
                    }
                    status.setText(entries.getChildCount() == 0
                            ? "Start a session to continue it here or on your computer."
                            : "Sessions opened from Meu on Android");
                    create.setEnabled(true);
                    refresh.setEnabled(true);
                });
            } catch (IOException | JSONException error) {
                onScreen(() -> {
                    if (root != page) return;
                    status.setText(sessionErrorText(error));
                    disconnect.setText("Pair again");
                    refresh.setEnabled(true);
                });
            }
        });
    }

    private interface SessionAttempt {
        JSONObject load() throws IOException, JSONException;
    }

    private void loadSession(LinearLayout page, Button create, Button refresh,
                             SessionAttempt attempt, boolean creating) {
        if (!create.isEnabled()) return;
        create.setEnabled(false);
        refresh.setEnabled(false);
        status.setText(creating ? "Creating session…" : "Opening session…");
        worker.execute(() -> {
            try {
                JSONObject session = attempt.load();
                String id = session.getString("id");
                onScreen(() -> {
                    if (root != page) return;
                    if (creating) newSessionRequest = null;
                    sessionId = id;
                    showChat(session);
                });
            } catch (IOException | JSONException error) {
                onScreen(() -> {
                    if (root != page) return;
                    create.setEnabled(true);
                    refresh.setEnabled(true);
                    status.setText(sessionErrorText(error));
                });
            }
        });
    }

    private void chatNavigation(Button leave) {
        leave.setText(client.supportsSessions() ? "Sessions" : "Change connection");
        leave.setOnClickListener(view -> {
            if (client.supportsSessions()) showSessions();
            else showConnection();
        });
    }

    private void showChat(JSONObject session) {
        screen(session == null ? "Android preview · Test conversation"
                : session.optString("title", "New session"));
        Button leave = button("Change connection");
        chatNavigation(leave);
        ScrollView scroll = new ScrollView(this);
        LinearLayout messages = new LinearLayout(this);
        messages.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(messages);
        EditText input = field("Write a message", InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE, 8000);
        input.setMaxLines(4);
        Button send = button("Send");
        status = label("Connected", 14, MUTED);
        JSONArray history = session == null ? null : session.optJSONArray("messages");
        if (history != null) {
            if (session.optBoolean("history_limited")) {
                messages.addView(label("Recent text only. Open this session on your computer for the full history.",
                        14, MUTED));
            }
            for (int index = 0; index < history.length(); index++) {
                JSONObject message = history.optJSONObject(index);
                if (message == null) continue;
                boolean user = "user".equals(message.optString("role"));
                messages.addView(label((user ? "You\n" : "Meu\n") + message.optString("content"), 16,
                        user ? ACCENT : INK));
            }
            scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
        }
        root.addView(leave);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        root.addView(status);
        root.addView(input);
        root.addView(send);
        send.setOnClickListener(view -> {
            if (pending == null) {
                String text = input.getText().toString().trim();
                if (text.isEmpty()) return;
                pending = new Pending(text);
                messages.addView(label("You\n" + text, 16, ACCENT));
                input.setText("");
            }
            sendTurn(input, send, leave, scroll, messages);
        });
    }

    private void sendTurn(EditText input, Button send, Button leave, ScrollView scroll, LinearLayout messages) {
        Pending turn = pending;
        if (SystemClock.elapsedRealtime() - turn.createdAt > RETRY_WINDOW_MS) {
            status.setText("This request is too old to resume. Check the conversation on your computer.");
            send.setEnabled(false);
            return;
        }
        MeuClient connected = client;
        String conversation = sessionId;
        send.setEnabled(false);
        leave.setEnabled(false);
        input.setEnabled(false);
        status.setText("Waiting for Meu…");
        worker.execute(() -> {
            try {
                JSONObject result = waitForResult(connected, conversation, turn);
                onScreen(() -> {
                    if (result == null) {
                        leave.setEnabled(true);
                        send.setEnabled(true);
                        send.setText("Resume request");
                        status.setText("Meu is still working. Resume this request to check for its reply.");
                        return;
                    }
                    String outcome = result.optString("status");
                    String answer = result.optString("output", "");
                    if (!answer.isEmpty()) messages.addView(label("Meu\n" + answer, 16, INK));
                    scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
                    pending = null;
                    leave.setEnabled(true);
                    chatNavigation(leave);
                    if ("unknown".equals(outcome)) {
                        status.setText("Meu lost the execution state. Review the run on your computer.");
                        return;
                    }
                    send.setText("Send");
                    send.setEnabled(true);
                    input.setEnabled(true);
                    status.setText("completed".equals(outcome) ? "Connected" : "Run ended: " + outcome);
                });
            } catch (IOException | JSONException error) {
                onScreen(() -> {
                    leave.setEnabled(true);
                    int code = httpStatus(error);
                    boolean paired = connected.usesPairing();
                    boolean closed = paired && (code == 401 || code == 410);
                    send.setEnabled(!closed);
                    send.setText("Resume request");
                    if (paired && code == 0) {
                        leave.setText("Pair again");
                        leave.setOnClickListener(view -> showConnection());
                        status.setText(error instanceof JSONException
                                ? "Could not read Meu's reply. Resume this request or pair again."
                                : "Connection to Meu lost. If both devices are still on the same network, "
                                    + "resume this request or pair again with a new code.");
                    } else if (closed) {
                        leave.setText("Pair again");
                        leave.setOnClickListener(view -> showConnection());
                        status.setText("This pairing has ended. Show a new code in Meu on your computer.");
                    } else {
                        status.setText(errorText(error));
                    }
                });
            } catch (InterruptedException stopped) {
                Thread.currentThread().interrupt();
            }
        });
    }

    private JSONObject waitForResult(MeuClient connected, String conversation, Pending turn)
            throws IOException, JSONException, InterruptedException {
        if (turn.runId == null) turn.runId = connected.submit(conversation, turn.input, turn.requestId);
        long deadline = SystemClock.elapsedRealtime() + 120_000;
        while (SystemClock.elapsedRealtime() < deadline) {
            JSONObject result = connected.status(turn.runId);
            switch (result.getString("status")) {
                case "completed": case "failed": case "cancelled": case "interrupted": case "unknown":
                    return result;
                case "started": case "queued": case "running": case "stopping":
                case "waiting_for_approval":
                    Thread.sleep(1800);
                    break;
                default:
                    throw new IOException("Unsupported run status");
            }
        }
        return null;
    }

    private void onScreen(Runnable action) {
        runOnUiThread(() -> { if (!isDestroyed()) action.run(); });
    }

    private static int httpStatus(Exception error) {
        return error instanceof MeuClient.HttpError ? ((MeuClient.HttpError) error).status : 0;
    }

    private static String pairingErrorText(Exception error) {
        int code = httpStatus(error);
        if (code == 401 || code == 410) {
            return "This pairing code has expired or was already used. Show a new code on your computer.";
        }
        return "Could not pair with Meu. Check that both devices are on the same local network "
                + "and scan a new code from your computer.";
    }

    private static String sessionErrorText(Exception error) {
        int code = httpStatus(error);
        if (code == 404) return "This session is no longer available. Refresh the list.";
        if (code == 401 || code == 410) return "This pairing ended. Show a new code on your computer.";
        return "Could not load the session. Check the local connection and try again.";
    }

    private static String errorText(Exception error) {
        int code = httpStatus(error);
        if (code != 0) {
            if (code == 401 || code == 403) {
                return "Access was refused. Try a new pairing code or check the gateway key.";
            }
            if (code == 410) return "This connection expired. Show a new pairing code on your computer.";
            return "The gateway returned HTTP " + code + ".";
        }
        return "No result yet. Check the HTTPS address, certificate and gateway connection.";
    }
}
