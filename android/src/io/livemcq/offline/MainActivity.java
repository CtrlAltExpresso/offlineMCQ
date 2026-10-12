package io.livemcq.offline;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.ScrollView;

import java.io.File;
import java.io.IOException;
import java.util.Locale;

public class MainActivity extends Activity implements DownloadService.Listener {

    private static final int REQ_NOTIF = 1001;

    private ContentManager cm;
    private AssetServer server;
    private WebView web;

    private EditText urlField;
    private TextView tvStatus;
    private TextView tvProgress;
    private TextView tvPercent;
    private ProgressBar progressBar;
    private View startButton;
    private View cancelButton;
    private ScrollView scroll;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        cm = new ContentManager(this);

        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                   != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIF);
        }

        if (cm.isReady()) {
            openViewer();
            maybeUpdate();
            return;
        }
        buildSetupUi();
        if (DownloadService.isRunning()) {
            showProgressUi("Restarting download…");
            DownloadService.setListener(this);
            return;
        }
        if (!Config.DEFAULT_MANIFEST_URL.isEmpty()) {
            startButton.post(this::startSync);
        }
    }

    // ---------------------------------------------------------------- setup

    private void buildSetupUi() {
        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(Color.WHITE);

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(40), dp(24), dp(24));
        box.setBackgroundColor(Color.WHITE);

        TextView title = new TextView(this);
        title.setText("LiveMCQ Offline");
        title.setTextSize(24);
        title.setTypeface(null, Typeface.BOLD);
        title.setTextColor(Color.parseColor("#1a237e"));
        box.addView(title);

        TextView sub = new TextView(this);
        sub.setText("One-time download of the full content (~9 GB).\nAfter it finishes, the app works fully offline — no internet needed.");
        sub.setTextSize(14);
        sub.setTextColor(Color.parseColor("#444444"));
        sub.setPadding(0, dp(6), 0, dp(18));
        box.addView(sub);

        TextView lbl = new TextView(this);
        lbl.setText("Content URL (livemcq_manifest.json)");
        lbl.setTextSize(13);
        lbl.setTextColor(Color.parseColor("#666666"));
        box.addView(lbl);

        urlField = new EditText(this);
        urlField.setSingleLine(true);
        urlField.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        urlField.setText(cm.savedUrl().isEmpty() ? Config.DEFAULT_MANIFEST_URL : cm.savedUrl());
        urlField.setTextSize(14);
        urlField.setPadding(dp(8), dp(6), dp(8), dp(6));
        box.addView(urlField);

        tvStatus = new TextView(this);
        tvStatus.setText("Requires ~" + String.format(Locale.US, "%.1f GB free storage.", 9.5));
        tvStatus.setTextSize(12);
        tvStatus.setTextColor(Color.parseColor("#888888"));
        tvStatus.setPadding(0, dp(4), 0, dp(12));
        box.addView(tvStatus);

        startButton = newButton("Start download", "#1a237e");
        startButton.setOnClickListener(v -> startSync());
        box.addView(startButton);

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(1000);
        progressBar.setVisibility(View.GONE);
        progressBar.setPadding(0, dp(16), 0, 0);
        box.addView(progressBar);

        tvProgress = new TextView(this);
        tvProgress.setTextSize(12);
        tvProgress.setTextColor(Color.parseColor("#222222"));
        tvProgress.setPadding(0, dp(6), 0, 0);
        tvProgress.setVisibility(View.GONE);
        box.addView(tvProgress);

        tvPercent = new TextView(this);
        tvPercent.setTextSize(26);
        tvPercent.setTypeface(null, Typeface.BOLD);
        tvPercent.setTextColor(Color.parseColor("#1a237e"));
        tvPercent.setVisibility(View.GONE);
        box.addView(tvPercent);

        cancelButton = newButton("Cancel", "#c62828");
        cancelButton.setVisibility(View.GONE);
        cancelButton.setOnClickListener(v -> DownloadService.cancel());
        box.addView(cancelButton);

        ScrollView scroll = new ScrollView(this);
        this.scroll = scroll;
        scroll.addView(box);
        frame.addView(scroll);
        setContentView(frame);
    }

    private View newButton(String text, String color) {
        TextView b = new TextView(this);
        b.setText(text);
        b.setTextSize(16);
        b.setGravity(Gravity.CENTER);
        b.setPadding(dp(12), dp(12), dp(12), dp(12));
        b.setBackgroundColor(Color.parseColor(color));
        b.setTextColor(Color.WHITE);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(10);
        b.setLayoutParams(lp);
        return b;
    }

    private void maybeUpdate() {
        new Thread(() -> {
            boolean upd;
            try {
                upd = cm.checkForUpdate();
            } catch (Exception e) {
                return;
            }
            if (upd) {
                runOnUiThread(() -> {
                    cm.clearReady();
                    buildSetupUi();
                    startSync();
                });
            }
        }, "content-update-check").start();
    }

    private void startSync() {
        String url = urlField.getText().toString().trim();
        if (url.isEmpty()) {
            tvStatus.setText("Please paste the manifest URL first.");
            tvStatus.setTextColor(Color.parseColor("#c62828"));
            return;
        }
        if (isMeteredData()) {
            new AlertDialog.Builder(this)
                    .setTitle("Mobile data warning")
                    .setMessage("You're on mobile data. This download is ~9 GB and may use a large amount of your data plan or incur charges. Continue?")
                    .setPositiveButton("Continue", (d, w) -> beginSync(url))
                    .setNegativeButton("Cancel", null)
                    .show();
        } else {
            beginSync(url);
        }
    }

    private void beginSync(String url) {
        DownloadService.setListener(this);
        showProgressUi("Contacting " + url);
        DownloadService.start(this, url);
    }

    private boolean isMeteredData() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) {
            return false;
        }
        if (Build.VERSION.SDK_INT >= 23) {
            NetworkCapabilities nc = cm.getNetworkCapabilities(cm.getActiveNetwork());
            if (nc != null && nc.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) {
                return !nc.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
            }
        }
        return false;
    }

    private void showProgressUi(String status) {
        urlField.setEnabled(false);
        startButton.setVisibility(View.GONE);
        progressBar.setVisibility(View.VISIBLE);
        tvProgress.setVisibility(View.VISIBLE);
        tvPercent.setVisibility(View.VISIBLE);
        progressBar.setIndeterminate(true);
        progressBar.setProgress(0);
        tvProgress.setText(status);
        tvPercent.setText("0%");
        cancelButton.setVisibility(View.VISIBLE);
        tvStatus.setText(status);
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
    }

    @Override
    public void onProgress(final long doneBytes, final long totalBytes, final String detail) {
        runOnUiThread(() -> {
            progressBar.setIndeterminate(false);
            double pct = totalBytes > 0 ? doneBytes * 100.0 / totalBytes : 0.0;
            tvPercent.setText(String.format(Locale.US, "%.1f%%", Math.min(100.0, pct)));
            progressBar.setProgress((int) Math.min(999, doneBytes * 1000 / Math.max(1, totalBytes)));
            tvProgress.setText(String.format(Locale.US, "%.2f / %.2f GB   %s",
                    doneBytes / 1073741824.0, totalBytes / 1073741824.0, detail));
        });
    }

    @Override
    public void onError(final String message) {
        runOnUiThread(() -> {
            tvStatus.setText(message);
            tvStatus.setTextColor(Color.parseColor("#c62828"));
            startButton.setVisibility(View.VISIBLE);
            urlField.setEnabled(true);
            cancelButton.setVisibility(View.GONE);
            tvPercent.setVisibility(View.GONE);
        });
    }

    @Override
    public void onDone() {
        runOnUiThread(() -> {
            tvStatus.setText("Done. Opening viewer…");
            openViewer();
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (cm != null && !cm.isReady() && DownloadService.isRunning()) {
            DownloadService.setListener(this);
        }
    }

    // ---------------------------------------------------------------- viewer

    private void openViewer() {
        File root = cm.contentRoot();
        try {
            server = AssetServer.start(root);
        } catch (IOException e) {
            if (web != null) {
                web.destroy();
            }
            finish();
            return;
        }

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        web.setWebViewClient(new LogClient());
        web.setWebChromeClient(new LogChrome());
        web.setKeepScreenOn(true);
        web.loadUrl("http://127.0.0.1:" + server.port() + "/viewer/index.html");
        setContentView(web);
    }

    @Override
    protected void onDestroy() {
        DownloadService.setListener(null);
        if (server != null) {
            server.stop();
        }
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    private int dp(int n) {
        return Math.round(n * getResources().getDisplayMetrics().density);
    }

    private static class LogClient extends WebViewClient {
        @Override
        public void onReceivedError(WebView v, android.webkit.WebResourceRequest r,
                                    android.webkit.WebResourceError e) {
            android.util.Log.e("LiveMCQWeb", "onReceivedError " + r.getUrl()
                    + " -> " + e.getErrorCode() + " " + e.getDescription());
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView v, android.webkit.WebResourceRequest r) {
            return external(v, r.getUrl() == null ? null : r.getUrl().toString());
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView v, String url) {
            return external(v, url);
        }

        /** Keep the local asset server + about: inside the WebView; send
         *  everything else (CDN streams, play store, mailto, …) to the system
         *  so a tapped link can't replace the whole viewer. */
        private boolean external(WebView v, String url) {
            if (url == null || url.isEmpty()
                    || url.startsWith("http://127.0.0.1:")
                    || url.startsWith("about:")
                    || url.startsWith("blob:")
                    || url.startsWith("data:")) {
                return false;
            }
            try {
                Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                v.getContext().startActivity(i);
            } catch (Exception e) {
                android.util.Log.e("LiveMCQWeb", "no activity for " + url);
            }
            return true;
        }
    }

    private static class LogChrome extends WebChromeClient {
        @Override
        public boolean onConsoleMessage(android.webkit.ConsoleMessage m) {
            android.util.Log.i("LiveMCQWeb", m.messageLevel() + " " + m.message()
                    + " @" + m.sourceId() + ":" + m.lineNumber());
            return true;
        }
    }
}