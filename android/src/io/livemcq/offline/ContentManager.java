package io.livemcq.offline;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.StatFs;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Downloads the chunked content bundle (manifest + .zip parts), verifies each
 * part's sha256 and extracts it under the internal files dir. Downloads use
 * HTTP Range resume into a temp file that survives restarts, so an
 * interrupted sync resumes where it stopped. Real-time cumulative progress
 * (bytes done across all parts) is streamed to the {@link Listener}; callers
 * only need to throttle UI refreshes.
 */
public final class ContentManager {

    public interface Listener {
        void onProgress(long doneBytes, long totalBytes, String detail);
        void onError(String message);
        void onDone();
    }

    private static final int WORKERS = 3;
    private static final int MAX_PART_RETRIES = 15;
    private static final long PROGRESS_INTERVAL_MS = 400;
    private static final String PREFS = "livemcq";
    private static final String KEY_URL = "manifest_url";
    private static final String KEY_READY = "content_ready";
    private static final String KEY_VERSION = "content_version";
    private static final String KEY_PARTS = "content_parts";

    private final Context ctx;
    private final File root;
    private final SharedPreferences prefs;
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private final AtomicBoolean userCancelled = new AtomicBoolean();
    private volatile String failure;
    private final AtomicLong downloaded = new AtomicLong();
    private final AtomicInteger nextPart = new AtomicInteger();
    private final long[] partLive;
    private volatile long lastProgress;
    private int totalParts;
    private ExecutorService pool;

    public ContentManager(Context ctx) {
        this.ctx = ctx.getApplicationContext();
        this.root = new File(this.ctx.getFilesDir(), "content");
        this.prefs = this.ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        this.partLive = new long[64];
        for (int i = 0; i < partLive.length; i++) {
            partLive[i] = -1;
        }
    }

    public File contentRoot() {
        return root;
    }

    private File doneDir() {
        return new File(root.getParentFile(), "done");
    }

    private File doneFile(int index) {
        return new File(doneDir(), "part_" + index + ".ok");
    }

    /**
     * A part counts as done only when its marker records the sha256 the
     * manifest currently advertises.
     *
     * Keying purely on the index meant that once a part had been fetched, a
     * later bundle which changed that part's content (e.g. an updated viewer
     * still packed as part_0017.zip) was never re-downloaded: every index
     * already had a marker, the sync downloaded nothing, then stamped the new
     * version as applied. The update silently did nothing.
     *
     * Unchanged parts still keep their marker, so an update only re-fetches the
     * parts that actually changed.
     *
     * Markers written by older builds contain the literal "ok" and carry no
     * hash. Such a marker is only trusted when the manifest marks the part
     * "carry": true — i.e. the builder verified the bytes are identical to the
     * previous release. That keeps the migration from a pre-hash install to a
     * couple of changed parts instead of the whole bundle.
     */
    private boolean isDone(int index, String sha, boolean carry) {
        File f = doneFile(index);
        if (!f.exists()) {
            return false;
        }
        if (sha == null || sha.isEmpty()) {
            return true;      // manifest carries no hash: trust the marker
        }
        String have = readMarker(f);
        if (have == null || have.isEmpty()) {
            return false;
        }
        if (have.equals("ok")) {
            return carry;
        }
        return have.equals(sha);
    }

    private static String readMarker(File f) {
        try (InputStream in = new FileInputStream(f)) {
            byte[] buf = new byte[128];
            int n = in.read(buf);
            return n <= 0 ? null : new String(buf, 0, n, "UTF-8").trim();
        } catch (IOException e) {
            return null;
        }
    }

    private void markDone(int index, String sha) {
        try {
            File d = doneDir();
            d.mkdirs();
            try (OutputStream o = new FileOutputStream(doneFile(index))) {
                String v = (sha == null || sha.isEmpty()) ? "ok" : sha;
                o.write(v.getBytes("UTF-8"));
                o.write('\n');
            }
        } catch (IOException ignored) {
        }
    }

    private static boolean carry(JSONObject part) {
        return part != null && part.optBoolean("carry", false);
    }

    private long baselineBytes(JSONArray parts) {
        long base = 0;
        for (int i = 0; i < parts.length(); i++) {
            JSONObject p = parts.optJSONObject(i);
            if (p != null && isDone(i, p.optString("sha256"), carry(p))) {
                base += p.optLong("size", 0);
            }
        }
        return base;
    }

    public boolean isReady() {
        return prefs.getBoolean(KEY_READY, false) && new File(root, ".ready").exists();
    }

    /** Drop the ready state so the next sync re-downloads only missing parts. */
    public void clearReady() {
        prefs.edit().putBoolean(KEY_READY, false).apply();
        new File(root, ".ready").delete();
    }

    /**
     * Fetch the manifest behind {@link #savedUrl()} and report whether it is a
     * newer revision than the one already applied (a version bump or a change
     * in the number of parts). Returns false when offline so the viewer keeps
     * working with no network.
     */
    public boolean checkForUpdate() {
        String url = savedUrl();
        if (url.isEmpty()) {
            return false;
        }
        JSONObject m = fetchJson(url);
        if (m == null) {
            return false;
        }
        int remoteVersion = m.optInt("version", 0);
        if (remoteVersion > prefs.getInt(KEY_VERSION, 0)) {
            return true;
        }
        JSONArray remoteParts = m.optJSONArray("parts");
        int remoteCount = remoteParts != null ? remoteParts.length() : 0;
        int storedCount = prefs.getInt(KEY_PARTS, 0);
        return remoteCount > 0 && remoteCount != storedCount;
    }

    public String savedUrl() {
        return prefs.getString(KEY_URL, "");
    }

    public boolean isSyncing() {
        return pool != null && !pool.isShutdown();
    }

    public long freeMegabytes() {
        StatFs sf = new StatFs(ctx.getFilesDir().getAbsolutePath());
        long bytes = (long) sf.getAvailableBlocks() * sf.getBlockSize();
        return bytes / (1024 * 1024);
    }

    public void cancel() {
        userCancelled.set(true);
        cancelled.set(true);
    }

    public void sync(final String manifestUrl, final Listener listener) {
        cancelled.set(false);
        userCancelled.set(false);
        failure = null;
        new Thread(() -> run(manifestUrl, listener), "content-sync").start();
    }

    private void run(String manifestUrl, Listener listener) {
        try {
            JSONObject manifest = fetchJson(manifestUrl.trim());
            if (manifest == null) {
                listener.onError("Could not read the manifest. Check the URL.");
                return;
            }
            JSONArray parts = manifest.optJSONArray("parts");
            if (parts == null || parts.length() == 0) {
                listener.onError("Manifest has no parts.");
                return;
            }
            long totalBytes = Math.max(manifest.optLong("total_bytes", 0), 1);
            totalParts = parts.length();
            String base = manifestUrl.substring(0, manifestUrl.lastIndexOf('/') + 1);

            long doneBytes = baselineBytes(parts);
            long neededMB = Math.max(0, totalBytes - doneBytes) / (1024 * 1024) + 1024;
            if (freeMegabytes() < neededMB) {
                listener.onError(String.format(Locale.US,
                        "Not enough free space (have %.1f GB, need ~%.1f GB). Free up space, then retry.",
                        freeMegabytes() / 1024.0, neededMB / 1024.0));
                return;
            }

            root.mkdirs();
            prefs.edit().putString(KEY_URL, manifestUrl).apply();
            downloaded.set(baselineBytes(parts));
            nextPart.set(0);
            lastProgress = 0;
            for (int i = 0; i < partLive.length; i++) {
                partLive[i] = -1;
            }

            AtomicInteger completed = new AtomicInteger(0);
            for (int i = 0; i < parts.length(); i++) {
                JSONObject p = parts.optJSONObject(i);
                if (p != null && isDone(i, p.optString("sha256"), carry(p))) {
                    completed.incrementAndGet();
                }
            }
            pool = Executors.newFixedThreadPool(WORKERS);
            for (int w = 0; w < WORKERS; w++) {
                pool.execute(() -> {
                    while (!cancelled.get()) {
                        int i = nextPart.getAndIncrement();
                        if (i >= parts.length()) {
                            return;
                        }
                        JSONObject part = parts.optJSONObject(i);
                        String file = part != null ? part.optString("file") : null;
                        if (file == null || file.isEmpty()) {
                            continue;
                        }
                        String sha = part.optString("sha256");
                        if (isDone(i, sha, carry(part))) {
                            continue;
                        }
                        long size = part.optLong("size", 0);
                        if (!process(i, base + file, file, sha, size, totalBytes, listener)) {
                            if (failure == null) {
                                failure = "Download failed: " + file;
                            }
                            cancelled.set(true);
                            return;
                        }
                        markDone(i, sha);
                        completed.incrementAndGet();
                        report(listener, totalBytes, String.format(Locale.US, "%d/%d parts done", completed.get(), parts.length()));
                    }
                });
            }
            pool.shutdown();
            pool.awaitTermination(8, TimeUnit.HOURS);
            if (userCancelled.get()) {
                listener.onError("Download cancelled.");
                return;
            }
            if (failure != null) {
                listener.onError(failure);
                return;
            }
            if (completed.get() != parts.length()) {
                return;
            }
            writeMarker();
            prefs.edit().putBoolean(KEY_READY, true)
                    .putInt(KEY_VERSION, manifest.optInt("version", 0))
                    .putInt(KEY_PARTS, parts.length()).apply();
            listener.onDone();
        } catch (Exception e) {
            listener.onError("Unexpected error: " + e.getMessage());
        } finally {
            if (pool != null) {
                pool.shutdownNow();
            }
        }
    }

private boolean process(int index, String partUrl, String file, String sha, long size,
                        long totalBytes, Listener listener) {
        File tmp = new File(root, file + ".part");
        for (int attempt = 0; attempt < MAX_PART_RETRIES; attempt++) {
            if (cancelled.get()) {
                return false;
            }
            try {
                long have = tmp.exists() ? tmp.length() : 0;
                partLive[index] = have;
                if (have > 0) {
                    report(listener, totalBytes, partLabel(index) + " (resuming)");
                }
                if (have < size || !valid(tmp, sha)) {
                    download(index, partUrl, tmp, size, have, totalBytes, listener);
                }
                if (!valid(tmp, sha)) {
                    tmp.delete();
                    partLive[index] = 0;
                    report(listener, totalBytes, partLabel(index) + " checksum mismatch, retrying");
                    continue;
                }
                report(listener, totalBytes, partLabel(index) + " extracting…");
                extract(tmp);
                downloaded.addAndGet(tmp.length());
                tmp.delete();
                partLive[index] = -1;
                return true;
            } catch (IOException e) {
                if (cancelled.get()) {
                    return false;
                }
                partLive[index] = tmp.exists() ? tmp.length() : -1;
                int wait = (int) Math.min(10000, 1000L * (attempt + 1));
                try {
                    Thread.sleep(wait);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return false;
                }
                if (cancelled.get()) {
                    return false;
                }
                report(listener, totalBytes, partLabel(index) + " retrying (" + (attempt + 1) + ")");
            }
        }
        return false;
    }

    private String partLabel(int index) {
        return "Part " + (index + 1) + "/" + totalParts;
    }

    private void download(int index, String partUrl, File tmp, long size, long have,
                          long totalBytes, Listener listener) throws IOException {
        HttpURLConnection conn = null;
        InputStream in = null;
        OutputStream out = null;
        try {
            try {
                conn = (HttpURLConnection) new URI(partUrl).toURL().openConnection();
            } catch (java.net.URISyntaxException e) {
                throw new IOException("bad URL: " + partUrl);
            }
            conn.setInstanceFollowRedirects(true);
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(45000);
            conn.setRequestProperty("User-Agent", "LiveMCQ-Recovery/1.0");
            conn.setRequestProperty("Range", "bytes=" + have + "-");
            int code = conn.getResponseCode();
            if (code != 200 && code != 206) {
                throw new IOException("HTTP " + code);
            }
            in = new BufferedInputStream(conn.getInputStream(), 256 * 1024);
            out = new BufferedOutputStream(new FileOutputStream(tmp, true), 256 * 1024);
            byte[] buf = new byte[128 * 1024];
            int r;
            while ((r = in.read(buf)) > 0) {
                out.write(buf, 0, r);
                partLive[index] = tmp.length();
                report(listener, totalBytes, partLabel(index));
            }
            out.flush();
        } finally {
            try { if (in != null) in.close(); } catch (IOException ignored) {}
            try { if (out != null) out.close(); } catch (IOException ignored) {}
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private void report(Listener l, long totalBytes, String detail) {
        long now = System.currentTimeMillis();
        if (now - lastProgress < PROGRESS_INTERVAL_MS && totalBytes > 0) {
            return;
        }
        lastProgress = now;
        long done = downloaded.get();
        synchronized (partLive) {
            for (long v : partLive) {
                if (v > 0) {
                    done += v;
                }
            }
        }
        l.onProgress(Math.min(done, totalBytes), totalBytes, detail);
    }

    private boolean valid(File f, String sha) {
        if (sha == null || sha.isEmpty()) {
            return true;
        }
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            try (InputStream in = new BufferedInputStream(new FileInputStream(f), 256 * 1024)) {
                byte[] buf = new byte[128 * 1024];
                int r;
                while ((r = in.read(buf)) > 0) {
                    md.update(buf, 0, r);
                }
            }
            StringBuilder sb = new StringBuilder(64);
            for (byte b : md.digest()) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString().equalsIgnoreCase(sha);
        } catch (IOException | NoSuchAlgorithmException e) {
            return false;
        }
    }

    private void extract(File part) throws IOException {
        try (ZipInputStream zin = new ZipInputStream(new BufferedInputStream(new FileInputStream(part), 256 * 1024))) {
            ZipEntry e;
            while ((e = zin.getNextEntry()) != null) {
                if (cancelled.get()) {
                    throw new IOException("cancelled");
                }
                if (!e.isDirectory()) {
                    File target = safe(root, e.getName());
                    File parent = target.getParentFile();
                    if (parent != null && !parent.exists() && !parent.mkdirs() && !parent.isDirectory()) {
                        throw new IOException("cannot create " + parent);
                    }
                    try (OutputStream fout = new BufferedOutputStream(new FileOutputStream(target), 128 * 1024)) {
                        byte[] buf = new byte[128 * 1024];
                        int r;
                        while ((r = zin.read(buf)) > 0) {
                            if (cancelled.get()) {
                                throw new IOException("cancelled");
                            }
                            fout.write(buf, 0, r);
                        }
                        fout.flush();
                    }
                }
                zin.closeEntry();
            }
        }
    }

    private static File safe(File root, String name) throws IOException {
        File target = root;
        for (String seg : name.split("/")) {
            if (seg.isEmpty() || seg.equals(".")) {
                continue;
            }
            if (seg.equals("..")) {
                throw new IOException("bad path");
            }
            target = new File(target, seg);
        }
        return target;
    }

    private static String name(String file) {
        int i = file.lastIndexOf('/');
        return i >= 0 ? file.substring(i + 1) : file;
    }

    private void writeMarker() throws IOException {
        File m = new File(root, ".ready");
        try (OutputStream out = new FileOutputStream(m)) {
            out.write("ok\n".getBytes("UTF-8"));
        }
    }

    private JSONObject fetchJson(String url) {
        String s = fetch(url);
        if (s == null) {
            return null;
        }
        try {
            return new JSONObject(s);
        } catch (Exception e) {
            return null;
        }
    }

    private String fetch(String url) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URI(url).toURL().openConnection();
            conn.setInstanceFollowRedirects(true);
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(45000);
            conn.setRequestProperty("User-Agent", "LiveMCQ-Recovery/1.0");
            if (conn.getResponseCode() != 200) {
                return null;
            }
            try (java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
                 InputStream in = conn.getInputStream()) {
                byte[] buf = new byte[8192];
                int r;
                while ((r = in.read(buf)) > 0) {
                    bos.write(buf, 0, r);
                }
                return bos.toString("UTF-8");
            }
        } catch (Exception e) {
            return null;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }
}