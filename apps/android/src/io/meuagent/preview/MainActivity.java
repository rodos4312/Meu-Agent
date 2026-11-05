package io.meuagent.preview;

import android.app.Activity;
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
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONException;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final int INK = 0xff15192b;
    private static final int MUTED = 0xff50576f;
    private static final int ACCENT = 0xff4541bb;
    private static final long RETRY_WINDOW_MS = 60 * 60 * 1000;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private LinearLayout root;
    private TextView status;
    private MeuClient client;
    private String sessionId;
    private Pending pending;

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
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
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
    }

    private void showConnection() {
        client = null;
        pending = null;
        screen("Connect to your Meu test gateway");
        EditText address = field("https://your-meu-gateway", InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_URI, 512);
        EditText key = field("Gateway access key", InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD, 512);
        key.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        Button connect = button("Connect");
        status = label("Use the HTTPS address of your test setup.", 14, MUTED);
        root.addView(address);
        root.addView(key);
        root.addView(connect);
        root.addView(status);
        connect.setOnClickListener(view -> connect(address, key, connect));
    }

    private void connect(EditText address, EditText key, Button connect) {
        final MeuClient candidate;
        try {
            String credential = key.getText().toString().trim();
            if (!credential.matches("[!-~]{1,512}")) {
                status.setText("Enter the test gateway access key.");
                return;
            }
            candidate = new MeuClient(MeuEndpoint.parse(address.getText().toString()), credential);
        } catch (IllegalArgumentException error) {
            status.setText("Enter an HTTPS address with a hostname and optional port.");
            return;
        }
        connect.setEnabled(false);
        status.setText("Checking the connection…");
        worker.execute(() -> {
            try {
                candidate.verify();
                onScreen(() -> {
                    key.setText("");
                    client = candidate;
                    sessionId = "meu-android-" + UUID.randomUUID();
                    showChat();
                });
            } catch (IOException | JSONException error) {
                onScreen(() -> {
                    connect.setEnabled(true);
                    status.setText(errorText(error));
                });
            }
        });
    }

    private void showChat() {
        screen("Android preview · Test conversation");
        Button leave = button("Change connection");
        leave.setOnClickListener(view -> showConnection());
        ScrollView scroll = new ScrollView(this);
        LinearLayout messages = new LinearLayout(this);
        messages.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(messages);
        EditText input = field("Write a message", InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_FLAG_MULTI_LINE, 8000);
        input.setMaxLines(4);
        Button send = button("Send");
        status = label("Connected", 14, MUTED);
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
                    String outcome = result.optString("status");
                    String answer = result.optString("output", "");
                    if (!answer.isEmpty()) messages.addView(label("Meu\n" + answer, 16, INK));
                    scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
                    pending = null;
                    leave.setEnabled(true);
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
                    send.setEnabled(true);
                    send.setText("Resume request");
                    status.setText(errorText(error));
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
        throw new IOException("Run still active");
    }

    private void onScreen(Runnable action) {
        runOnUiThread(() -> { if (!isDestroyed()) action.run(); });
    }

    private static String errorText(Exception error) {
        if (error instanceof MeuClient.HttpError) {
            int code = ((MeuClient.HttpError) error).status;
            if (code == 401 || code == 403) return "The gateway refused access. Check the access key.";
            return "The gateway returned HTTP " + code + ".";
        }
        return "No result yet. Check the HTTPS address, certificate and gateway connection.";
    }
}
