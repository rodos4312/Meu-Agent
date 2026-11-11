package io.meuagent.preview;

import android.app.Activity;
import android.app.AlertDialog;
import android.Manifest;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
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
import java.util.Locale;
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
    private final Handler ui = new Handler(Looper.getMainLooper());
    private LinearLayout root;
    private TextView status;
    private MeuClient client;
    private String sessionId;
    private String newSessionRequest;
    private Pending pending;
    private MeuQrScanner scanner;
    private SavedMeuConnection savedConnection;
    private Runnable chatRefresh;
    private boolean foreground;
    private JSONArray lastCodingTasks;
    private long lastCodingSync;

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
        savedConnection = new SavedMeuConnection(this);
        if (savedConnection.exists()) reconnect();
        else showConnection();
    }

    @Override protected void onDestroy() {
        worker.shutdownNow();
        super.onDestroy();
    }

    @Override protected void onPause() {
        foreground = false;
        if (chatRefresh != null) ui.removeCallbacks(chatRefresh);
        if (scanner != null) scanner.stop();
        super.onPause();
    }

    @Override protected void onResume() {
        super.onResume();
        foreground = true;
        if (chatRefresh != null) chatRefresh.run();
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
        if (chatRefresh != null) {
            ui.removeCallbacks(chatRefresh);
            chatRefresh = null;
        }
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
        savedConnection.forget();
        client = null;
        pending = null;
        newSessionRequest = null;
        showPairing(null, "");
    }

    private void reconnect() {
        screen("Reconnecting to your computer");
        LinearLayout page = root;
        TextView message = label("Checking the saved connection…", 14, MUTED);
        Button retry = button("Retry connection");
        Button pairAgain = button("Pair again");
        retry.setEnabled(false);
        retry.setOnClickListener(view -> reconnect());
        pairAgain.setOnClickListener(view -> showConnection());
        root.addView(message);
        root.addView(retry);
        root.addView(pairAgain);
        worker.execute(() -> {
            try {
                MeuClient candidate = MeuClient.reconnect(savedConnection.load());
                JSONObject session = restoreSession(candidate, savedConnection.lastSession());
                onScreen(() -> {
                    if (root != page) return;
                    client = candidate;
                    if (session == null) showSessions();
                    else {
                        sessionId = session.optString("id");
                        showChat(session);
                    }
                });
            } catch (GeneralSecurityException | IllegalArgumentException error) {
                onScreen(() -> {
                    if (root != page) return;
                    message.setText("This saved pairing is no longer available. Show a new QR code on your computer.");
                });
            } catch (IOException | JSONException error) {
                onScreen(() -> {
                    if (root != page) return;
                    message.setText(sessionErrorText(error));
                    retry.setEnabled(true);
                });
            }
        });
    }

    private static JSONObject restoreSession(MeuClient candidate, String id) throws IOException, JSONException {
        if (id.isEmpty()) return null;
        try {
            return candidate.openSession(id);
        } catch (MeuClient.HttpError error) {
            if (error.status == 404) return null;
            throw error;
        }
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
                connect(() -> {
                    MeuClient candidate = MeuClient.pair(pairing);
                    if (pairing.oneTime && candidate.supportsSessions()) {
                        try {
                            savedConnection.save(candidate.rememberedCode(pairing));
                        } catch (GeneralSecurityException | IOException error) {
                            onScreen(() -> android.widget.Toast.makeText(this,
                                    "Connected, but Android could not save this pairing.", android.widget.Toast.LENGTH_LONG).show());
                        }
                    }
                    return candidate;
                }, true, code, pair, manual, scan);
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
        Button coding = button("Coding approvals");
        coding.setOnClickListener(view -> showCodingTasks());
        root.addView(create);
        root.addView(refresh);
        root.addView(coding);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        root.addView(status);
        root.addView(disconnect);

        create.setOnClickListener(view -> {
            if (newSessionRequest == null) newSessionRequest = UUID.randomUUID().toString();
            String requestId = newSessionRequest;
            loadSession(page, create, refresh, () -> {
                JSONObject created = connected.createSession(requestId);
                return connected.openSession(created.getString("id"));
            }, true);
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
                    if (savedConnection.exists()) savedConnection.rememberSession(id);
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
        if (session != null) {
            renderHistory(session, messages);
            scroll.post(() -> scroll.scrollTo(0, messages.getHeight()));
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
        if (session != null && session.optString("revision").matches("[0-9a-f]{64}")) {
            watchChat(session.optString("revision"), scroll, messages);
        }
    }

    private void renderHistory(JSONObject session, LinearLayout messages) {
        JSONArray history = session.optJSONArray("messages");
        if (history == null) return;
        messages.removeAllViews();
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
    }

    private void watchChat(String initialRevision, ScrollView scroll, LinearLayout messages) {
        MeuClient connected = client;
        String conversation = sessionId;
        chatRefresh = new Runnable() {
            private String revision = initialRevision;
            private boolean refreshing;

            @Override public void run() {
                if (!foreground || chatRefresh != this || refreshing) return;
                if (pending != null) {
                    ui.postDelayed(this, 3000);
                    return;
                }
                refreshing = true;
                worker.execute(() -> {
                    try {
                        JSONObject session = connected.openSession(conversation, revision);
                        onScreen(() -> receive(session));
                    } catch (IOException | JSONException error) {
                        int code = httpStatus(error);
                        onScreen(() -> {
                            refreshing = false;
                            if (!foreground || chatRefresh != this) return;
                            if (pending == null && (code == 401 || code == 410 || code == 404)) {
                                status.setText(sessionErrorText(error));
                            } else {
                                ui.postDelayed(this, 8000);
                            }
                        });
                    }
                });
            }

            private void receive(JSONObject session) {
                refreshing = false;
                if (!foreground || chatRefresh != this) return;
                if (pending == null && session.has("messages")) {
                    int position = scroll.getScrollY();
                    boolean atEnd = !scroll.canScrollVertically(1);
                    renderHistory(session, messages);
                    revision = session.optString("revision");
                    scroll.post(() -> scroll.scrollTo(0, atEnd ? messages.getHeight() : position));
                }
                ui.postDelayed(this, 3000);
            }
        };
        if (foreground) ui.postDelayed(chatRefresh, 3000);
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
                                : "Connection to Meu lost. Check your Wi-Fi or mobile data, "
                                    + "then resume this request or pair again.");
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

    // ── Coding approvals ────────────────────────────────────────────────────────
    // The PC owns every coding task. This screen only shows the PC's current state and sends
    // decisions naming the exact approval id + fingerprint on screen; the PC refuses anything
    // stale or already decided. No commit, integration, push or merge exists here.

    private interface CodingRequest {
        JSONObject build() throws JSONException;
    }

    private LinearLayout vertical() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    private void showCodingTasks() {
        screen("Coding · approvals from your PC");
        LinearLayout page = root;
        MeuClient connected = client;
        LinearLayout entries = vertical();
        ScrollView scroll = new ScrollView(this);
        scroll.addView(entries);
        status = label("Loading coding tasks…", 14, MUTED);
        Button refresh = button("Refresh");
        Button back = button("Sessions");
        refresh.setOnClickListener(view -> showCodingTasks());
        back.setOnClickListener(view -> showSessions());
        root.addView(refresh);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        root.addView(status);
        root.addView(back);
        if (lastCodingTasks != null) renderCodingRows(entries, lastCodingTasks);
        worker.execute(() -> {
            try {
                JSONArray tasks = connected.coding(new JSONObject().put("op", "list")).getJSONArray("tasks");
                onScreen(() -> {
                    if (root != page) return;
                    lastCodingTasks = tasks;
                    lastCodingSync = System.currentTimeMillis();
                    entries.removeAllViews();
                    renderCodingRows(entries, tasks);
                    status.setText(tasks.length() == 0 ? "No coding tasks on your PC." : "PC online · up to date");
                });
            } catch (IOException | JSONException error) {
                onScreen(() -> {
                    if (root != page) return;
                    status.setText(codingErrorText(error));
                });
            }
        });
    }

    private void renderCodingRows(LinearLayout entries, JSONArray tasks) {
        for (int index = 0; index < tasks.length(); index++) {
            JSONObject item = tasks.optJSONObject(index);
            if (item == null) continue;
            String id = item.optString("task_id");
            Button open = button(item.optString("label") + " · " + item.optString("project") + "\n"
                    + item.optString("description"));
            open.setOnClickListener(view -> showCodingTask(id));
            entries.addView(open);
        }
    }

    private String codingErrorText(Exception error) {
        int code = httpStatus(error);
        if (code == 409 && error instanceof MeuClient.HttpError && !((MeuClient.HttpError) error).reason.isEmpty()) {
            return ((MeuClient.HttpError) error).reason;
        }
        if (code == 401 || code == 410) return "This pairing ended. Show a new code on your computer.";
        if (code == 404) return "This coding task is no longer on your PC.";
        String when = lastCodingSync == 0 ? "" : " Last synced "
                + DateFormat.getTimeInstance(DateFormat.SHORT).format(new Date(lastCodingSync)) + ".";
        return "PC offline or unreachable — nothing runs from here until it is back. "
                + "Pending approvals stay pending on the PC." + when;
    }

    private void showCodingTask(String taskId) {
        screen("Coding task");
        LinearLayout page = root;
        MeuClient connected = client;
        LinearLayout body = vertical();
        ScrollView scroll = new ScrollView(this);
        scroll.addView(body);
        status = label("Loading…", 14, MUTED);
        Button back = button("Coding tasks");
        back.setOnClickListener(view -> showCodingTasks());
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        root.addView(status);
        root.addView(back);
        codingCall(page, body, connected, () -> new JSONObject().put("op", "get").put("task_id", taskId));
    }

    private void codingCall(LinearLayout page, LinearLayout body, MeuClient connected, CodingRequest request) {
        status.setText("Contacting your PC…");
        worker.execute(() -> {
            try {
                JSONObject task = connected.coding(request.build()).getJSONObject("task");
                lastCodingSync = System.currentTimeMillis();
                onScreen(() -> {
                    if (root != page) return;
                    try {
                        renderCodingTask(page, body, connected, task);
                        status.setText("PC online · up to date");
                    } catch (JSONException error) {
                        status.setText("Could not read this coding task.");
                    }
                });
            } catch (IOException | JSONException error) {
                onScreen(() -> {
                    if (root != page) return;
                    status.setText(codingErrorText(error));
                });
            }
        });
    }

    private void addFact(LinearLayout body, String name, String value) {
        if (value == null || value.isEmpty()) return;
        TextView view = label(name + ": " + value, 14, INK);
        view.setPadding(0, dp(2), 0, dp(2));
        body.addView(view);
    }

    private static String joined(JSONArray items) {
        if (items == null || items.length() == 0) return "";
        StringBuilder text = new StringBuilder();
        for (int index = 0; index < items.length(); index++) {
            if (index > 0) text.append(", ");
            text.append(items.optString(index));
        }
        return text.toString();
    }

    private static String shortFingerprint(String fingerprint) {
        return fingerprint.length() > 16
                ? fingerprint.substring(0, 8) + "…" + fingerprint.substring(fingerprint.length() - 8) : fingerprint;
    }

    private JSONObject decisionBody(String taskId, JSONObject approval, String decision) throws JSONException {
        return new JSONObject().put("op", "decide").put("task_id", taskId)
                .put("approval_id", approval.getString("approval_id"))
                .put("fingerprint", approval.getString("fingerprint")).put("decision", decision);
    }

    private void renderCodingTask(LinearLayout page, LinearLayout body, MeuClient connected, JSONObject task)
            throws JSONException {
        body.removeAllViews();
        String taskId = task.getString("task_id");
        TextView stage = label(task.optString("label"), 20, INK);
        stage.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        body.addView(stage);
        body.addView(label(task.optString("project") + " · " + task.optString("description"), 15, INK));
        if (!task.optString("error").isEmpty()) body.addView(label(task.optString("error"), 14, 0xffb3261e));
        JSONObject pc = task.optJSONObject("pc");
        String branch = pc == null ? "" : pc.optString("worktree_branch");
        addFact(body, "PC", "online" + (pc != null && pc.optBoolean("busy") ? " · working" : "")
                + (branch.isEmpty() ? "" : " · " + branch));
        addFact(body, "Risk", task.optString("risk").toUpperCase(Locale.ROOT));
        addFact(body, "Files", joined(task.optJSONArray("files")));
        addFact(body, "Plan", task.optString("summary"));
        addFact(body, "Tests expected", joined(task.optJSONArray("tests_expected")));
        JSONObject actions = task.getJSONObject("actions");
        JSONObject approval = task.optJSONObject("approval");
        if (approval != null) {
            addFact(body, "Fingerprint", shortFingerprint(approval.getString("fingerprint")));
            renderDiff(page, body, connected, taskId, "proposed", "Proposed changes", approval.optJSONObject("proposed"));
            if (actions.optBoolean("approve")) {
                Button approve = button("Approve " + shortFingerprint(approval.getString("fingerprint")));
                Button reject = button("Reject");
                approve.setOnClickListener(view -> codingCall(page, body, connected,
                        () -> decisionBody(taskId, approval, "approve")));
                reject.setOnClickListener(view -> codingCall(page, body, connected,
                        () -> decisionBody(taskId, approval, "reject")));
                body.addView(approve);
                body.addView(reject);
            }
        }
        JSONObject result = task.optJSONObject("result");
        if (result != null) renderCodingResult(page, body, connected, taskId, result, actions);
        JSONObject remote = task.optJSONObject("remote");
        if (remote != null) renderCodingRemote(page, body, connected, taskId, remote);
        renderCodingDetails(body, task, approval);
        if (task.optBoolean("busy")) {
            chatRefresh = () -> {
                if (root == page && foreground) {
                    codingCall(page, body, connected, () -> new JSONObject().put("op", "get").put("task_id", taskId));
                }
            };
            ui.postDelayed(chatRefresh, 3000);
        }
    }

    private void renderCodingResult(LinearLayout page, LinearLayout body, MeuClient connected, String taskId,
                                    JSONObject result, JSONObject actions) {
        addFact(body, "Changed", joined(result.optJSONArray("files_changed")) + " (+" + result.optInt("additions")
                + " −" + result.optInt("deletions") + ")");
        JSONArray tests = result.optJSONArray("tests");
        for (int index = 0; tests != null && index < tests.length(); index++) {
            JSONObject test = tests.optJSONObject(index);
            if (test != null) addFact(body, test.optString("status"), test.optString("check"));
        }
        JSONObject reviewer = result.optJSONObject("reviewer");
        if (reviewer != null) {
            addFact(body, "Reviewer", reviewer.optString("verdict").toUpperCase(Locale.ROOT) + " — "
                    + reviewer.optString("rationale"));
        }
        renderDiff(page, body, connected, taskId, "actual", "Actual changes", result.optJSONObject("actual"));
        if (actions.optBoolean("keep")) {
            Button keep = button("Keep");
            keep.setOnClickListener(view -> codingCall(page, body, connected,
                    () -> new JSONObject().put("op", "keep").put("task_id", taskId)));
            body.addView(keep);
        }
        if (actions.optBoolean("reject") && !actions.optBoolean("approve")) {
            Button reject = button("Reject result");
            reject.setOnClickListener(view -> codingCall(page, body, connected,
                    () -> new JSONObject().put("op", "reject").put("task_id", taskId)));
            body.addView(reject);
        }
    }

    // Remote push / PR / merge: the PC prepares each preview; the phone approves exactly that
    // preview (kind + full fingerprint) after an explicit confirmation. Each is its own approval.
    private static final String[][] REMOTE_KINDS = {
        {"push", "push_preview", "Approve push"},
        {"pr", "pr_preview", "Approve PR creation"},
        {"merge", "merge_preview", "Approve merge"},
    };

    private void renderCodingRemote(LinearLayout page, LinearLayout body, MeuClient connected, String taskId,
                                    JSONObject remote) {
        TextView title = label("Remote · " + remote.optString("label"), 16, INK);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        body.addView(title);
        if (!remote.optString("repository").isEmpty()) addFact(body, "Repository", remote.optString("repository"));
        if (!remote.optBoolean("available") && !remote.optString("reason").isEmpty()) {
            body.addView(label(remote.optString("reason"), 14, MUTED));
        }
        if (!remote.optString("blocked").isEmpty()) body.addView(label(remote.optString("blocked"), 14, 0xffb3261e));
        JSONObject pr = remote.optJSONObject("pr");
        if (pr != null) addFact(body, "Pull request", "#" + pr.optInt("number") + " · " + pr.optString("state"));
        JSONObject status = remote.optJSONObject("pr_status");
        if (status != null) {
            JSONObject checks = status.optJSONObject("checks");
            JSONObject reviews = status.optJSONObject("reviews");
            addFact(body, "Checks", checks == null ? "" : checks.optString("state"));
            addFact(body, "Reviews", reviews == null ? "" : reviews.optInt("approvals") + " approval(s), "
                    + reviews.optInt("changes_requested") + " change request(s)");
        }
        JSONObject merged = remote.optJSONObject("merged");
        if (merged != null) {
            addFact(body, "Merged", merged.optString("method") + " · " + merged.optString("merge_commit")
                    + (merged.optBoolean("target_verified") ? " · target verified" : " · target NOT verified"));
        }
        JSONObject approve = remote.optJSONObject("approve");
        for (String[] kind : REMOTE_KINDS) {
            JSONObject preview = remote.optJSONObject(kind[1]);
            if (preview == null) continue;
            renderRemotePreview(body, kind[0], preview);
            if (approve == null || !approve.optBoolean(kind[0])) continue;
            String fingerprint = preview.optString("fingerprint");
            Button button = button(kind[2] + " " + shortFingerprint(fingerprint));
            button.setOnClickListener(view -> new AlertDialog.Builder(this)
                    .setTitle(kind[2] + "?")
                    .setMessage(remoteSummary(kind[0], preview) + "\n\nFingerprint " + shortFingerprint(fingerprint))
                    .setNegativeButton("Cancel", null)
                    .setPositiveButton("Approve", (dialog, which) -> codingCall(page, body, connected,
                            () -> new JSONObject().put("op", "remote_approve").put("task_id", taskId)
                                    .put("kind", kind[0]).put("fingerprint", fingerprint).put("confirmed", true)))
                    .show());
            body.addView(button);
        }
        if (pr != null) {
            Button refresh = button("Refresh pull request");
            refresh.setOnClickListener(view -> codingCall(page, body, connected,
                    () -> new JSONObject().put("op", "remote_refresh").put("task_id", taskId)));
            body.addView(refresh);
        }
    }

    private void renderRemotePreview(LinearLayout body, String kind, JSONObject preview) {
        if ("push".equals(kind)) {
            addFact(body, "Push", preview.optString("source_branch") + " @ " + preview.optString("new_sha"));
            addFact(body, "To", preview.optString("remote") + " · " + preview.optString("destination_branch"));
            addFact(body, "Force", preview.optBoolean("force_required") ? "required — blocked" : "forbidden");
        } else if ("pr".equals(kind)) {
            addFact(body, "PR title", preview.optString("title"));
            addFact(body, "Head → base", preview.optString("source_branch") + " → " + preview.optString("target_branch"));
        } else {
            addFact(body, "Merge", "PR #" + preview.optInt("pr_number") + " · " + preview.optString("method")
                    + " → " + preview.optString("target_branch"));
            addFact(body, "Status", preview.optString("status"));
            addFact(body, "Head / target", preview.optString("source_sha") + " / " + preview.optString("target_sha"));
            JSONArray reasons = preview.optJSONArray("reasons");
            if (reasons != null && reasons.length() > 0) addFact(body, "Why", joined(reasons));
        }
        addFact(body, "Risk", preview.optString("risk").toUpperCase(Locale.ROOT));
        addFact(body, "Files", joined(preview.optJSONArray("changed_files")));
    }

    private static String remoteSummary(String kind, JSONObject preview) {
        if ("push".equals(kind)) {
            return "Push " + preview.optString("refspec") + " to " + preview.optString("remote") + ". No force.";
        }
        if ("pr".equals(kind)) {
            return "Create PR \"" + preview.optString("title") + "\" on " + preview.optString("repository") + ".";
        }
        return "Merge PR #" + preview.optInt("pr_number") + " (" + preview.optString("method") + ") into "
                + preview.optString("target_branch") + " at " + preview.optString("source_sha") + ".";
    }

    private void renderCodingDetails(LinearLayout body, JSONObject task, JSONObject approval) throws JSONException {
        LinearLayout details = vertical();
        details.setVisibility(View.GONE);
        if (approval != null) {
            addFact(details, "Approval", approval.getString("approval_id"));
            addFact(details, "Full fingerprint", approval.getString("fingerprint"));
            addFact(details, "Edit strategy", approval.optString("strategy"));
        }
        JSONArray decisions = task.optJSONArray("decisions");
        for (int index = 0; decisions != null && index < decisions.length(); index++) {
            JSONObject decision = decisions.optJSONObject(index);
            if (decision != null) addFact(details, decision.optString("decision"), "from " + decision.optString("source"));
        }
        Button toggle = button("View details");
        toggle.setOnClickListener(view -> {
            boolean hidden = details.getVisibility() != View.VISIBLE;
            details.setVisibility(hidden ? View.VISIBLE : View.GONE);
            toggle.setText(hidden ? "Hide details" : "View details");
        });
        body.addView(toggle);
        body.addView(details);
    }

    private TextView diffLine(String line) {
        TextView view = label(line, 12, line.startsWith("+") ? 0xff1b7a3a : line.startsWith("-") ? 0xffb3261e
                : line.startsWith("@@") ? ACCENT : MUTED);
        view.setTypeface(Typeface.MONOSPACE);
        view.setPadding(0, 0, 0, 0);
        return view;
    }

    private void renderDiff(LinearLayout page, LinearLayout body, MeuClient connected, String taskId, String which,
                            String title, JSONObject summary) {
        if (summary == null) return;
        TextView heading = label(title, 16, INK);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        body.addView(heading);
        JSONArray files = summary.optJSONArray("files");
        for (int index = 0; files != null && index < files.length(); index++) {
            JSONObject file = files.optJSONObject(index);
            if (file == null) continue;
            String filePath = file.optString("path");
            TextView name = label(filePath + "   +" + file.optInt("additions") + " −" + file.optInt("deletions"), 14, INK);
            name.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
            body.addView(name);
            LinearLayout lines = vertical();
            JSONArray shown = file.optJSONArray("lines");
            for (int line = 0; shown != null && line < shown.length(); line++) lines.addView(diffLine(shown.optString(line)));
            body.addView(lines);
            if (file.optBoolean("truncated")) {
                Button more = button("Show full diff of " + filePath);
                more.setOnClickListener(view -> worker.execute(() -> {
                    try {
                        JSONObject full = connected.coding(new JSONObject().put("op", "diff").put("task_id", taskId)
                                .put("which", which).put("path", filePath));
                        JSONArray all = full.getJSONArray("lines");
                        onScreen(() -> {
                            if (root != page) return;
                            lines.removeAllViews();
                            for (int line = 0; line < all.length(); line++) lines.addView(diffLine(all.optString(line)));
                            more.setVisibility(View.GONE);
                        });
                    } catch (IOException | JSONException error) {
                        onScreen(() -> { if (root == page) status.setText(codingErrorText(error)); });
                    }
                }));
                body.addView(more);
            }
        }
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
        return "Could not pair with Meu. Check that the computer is online and scan a new code.";
    }

    private static String sessionErrorText(Exception error) {
        int code = httpStatus(error);
        if (code == 404) return "This session is no longer available. Refresh the list.";
        if (code == 401 || code == 410) return "This pairing ended. Show a new code on your computer.";
        return "Could not load the session. Check your connection to Meu and try again.";
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
