package io.livemcq.offline;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Tiny HTTP/1.0 server bound to 127.0.0.1 that streams the extracted content
 * tree (viewer/ + media host dirs) from the app's internal storage to the
 * WebView. Paths are mapped 1:1, traversal is rejected.
 */
public final class AssetServer {

    public static final String HOME_PAGE = "/viewer/index.html";

    private final File root;
    private final ServerSocket socket;
    private final ExecutorService workers;

    private AssetServer(File root, ServerSocket socket) {
        this.root = root;
        this.socket = socket;
        this.workers = Executors.newCachedThreadPool();
        Thread th = new Thread(this::acceptLoop, "asset-server");
        th.setDaemon(true);
        th.start();
    }

    public static AssetServer start(File root) throws IOException {
        IOException last = null;
        for (int port = 8667; port < 8777; port++) {
            try {
                ServerSocket ss = new ServerSocket(port, 8, InetAddress.getByName("127.0.0.1"));
                return new AssetServer(root, ss);
            } catch (IOException e) {
                last = e;
            }
        }
        throw last != null ? last : new IOException("no free loopback port");
    }

    public int port() {
        return socket.getLocalPort();
    }

    public void stop() {
        try {
            socket.close();
        } catch (IOException ignored) {
        }
        workers.shutdownNow();
    }

    private void acceptLoop() {
        while (!socket.isClosed()) {
            try {
                Socket s = socket.accept();
                workers.execute(() -> handle(s));
            } catch (IOException ignored) {
            }
        }
    }

    private void handle(Socket client) {
        try (Socket s = client) {
            s.setSoTimeout(30000);
            s.setTcpNoDelay(true);
            InputStream reqIn = s.getInputStream();
            String line = readLine(reqIn);
            if (line == null) {
                return;
            }
            // Drain the rest of the request headers, capturing Range. Closing a
            // socket while the peer's bytes are still unread makes the kernel send
            // RST instead of FIN, which the WebView reports as
            // net::ERR_CONNECTION_RESET and the page load silently dies.
            String rangeHeader = null;
            String header;
            while ((header = readLine(reqIn)) != null && header.length() > 0) {
                int c = header.indexOf(':');
                if (c > 0 && header.substring(0, c).trim().equalsIgnoreCase("Range")) {
                    rangeHeader = header.substring(c + 1).trim();
                }
            }
            String[] parts = line.split(" ");
            if (parts.length < 2) {
                return;
            }
            String method = parts[0].toUpperCase();
            if (!"GET".equals(method) && !"HEAD".equals(method)) {
                respond(s.getOutputStream(), 501, "text/plain; charset=utf-8", -1);
                return;
            }
            File target = map(parts[1]);
            if (target == null || !target.isFile()) {
                respond(s.getOutputStream(), 404, "text/plain; charset=utf-8", -1);
                return;
            }
            OutputStream out = s.getOutputStream();
            long len = target.length();
            long start = 0, end = len - 1;
            boolean partial = false;
            if (rangeHeader != null && !rangeHeader.isEmpty()) {
                long[] r = parseRange(rangeHeader, len);
                if (r == null) {
                    String h = "HTTP/1.1 416 Range Not Satisfiable\r\n"
                            + "Content-Range: bytes */" + len + "\r\n"
                            + "Content-Length: 0\r\nConnection: close\r\n\r\n";
                    out.write(h.getBytes("ISO-8859-1"));
                    out.flush();
                    return;
                }
                start = r[0];
                end = r[1];
                partial = true;
            }
            long length = end - start + 1;
            StringBuilder hb = new StringBuilder();
            hb.append(partial ? "HTTP/1.1 206 Partial Content\r\n" : "HTTP/1.1 200 OK\r\n")
              .append("Content-Type: ").append(mime(target.getName())).append("\r\n")
              .append("Content-Length: ").append(length).append("\r\n")
              .append("Accept-Ranges: bytes\r\n");
            if (partial) {
                hb.append("Content-Range: bytes ").append(start).append('-').append(end)
                  .append('/').append(len).append("\r\n");
            }
            hb.append("Connection: close\r\nCache-Control: no-store\r\n\r\n");
            out.write(hb.toString().getBytes("ISO-8859-1"));
            if ("HEAD".equals(method)) {
                out.flush();
                return;
            }
            try (InputStream in = new BufferedInputStream(new FileInputStream(target), 256 * 1024)) {
                byte[] buf = new byte[128 * 1024];
                long skip = start;
                while (skip > 0) {
                    long sk = in.skip(skip);
                    if (sk <= 0) {
                        break;
                    }
                    skip -= sk;
                }
                long remaining = length;
                int r;
                while (remaining > 0 && (r = in.read(buf, 0, (int) Math.min(buf.length, remaining))) > 0) {
                    if (s.isClosed()) {
                        return;
                    }
                    out.write(buf, 0, r);
                    remaining -= r;
                }
                out.flush();
            }
        } catch (IOException ignored) {
        }
    }

    /**
     * Parse a single-range "bytes=a-b" / "bytes=a-" / "bytes=-n" header.
     * Returns {start, end} inclusive, or null if unsatisfiable / unusable.
     */
    private static long[] parseRange(String h, long len) {
        if (!h.startsWith("bytes=") || len <= 0) {
            return null;
        }
        String spec = h.substring(6);
        int comma = spec.indexOf(',');
        if (comma >= 0) {
            spec = spec.substring(0, comma);
        }
        spec = spec.trim();
        int dash = spec.indexOf('-');
        if (dash < 0) {
            return null;
        }
        try {
            String a = spec.substring(0, dash).trim();
            String b = spec.substring(dash + 1).trim();
            long start, end;
            if (a.isEmpty()) {
                long n = Long.parseLong(b);
                if (n <= 0) {
                    return null;
                }
                start = Math.max(0, len - n);
                end = len - 1;
            } else {
                start = Long.parseLong(a);
                end = b.isEmpty() ? len - 1 : Long.parseLong(b);
            }
            if (end > len - 1) {
                end = len - 1;
            }
            if (start < 0 || start > end || start >= len) {
                return null;
            }
            return new long[]{start, end};
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /**
     * Map a request path to a file. Disk filenames are stored as their literal
     * percent-escaped strings (safe filenames), and browsers transmit those
     * escapes verbatim, so we match the RAW path without decoding. Only the
     * root (or a bare directory) maps to the viewer home page.
     */
    private File map(String rawPath) {
        if (rawPath == null) {
            return null;
        }
        String path = rawPath;
        int q = path.indexOf('?');
        if (q >= 0) {
            path = path.substring(0, q);
        }
        path = path.replace('\\', '/');
        while (path.startsWith("/")) {
            path = path.substring(1);
        }
        if (path.isEmpty()) {
            return new File(root, HOME_PAGE.substring(1));
        }
        for (String seg : path.split("/")) {
            if (seg.equals("..") || seg.indexOf('\0') >= 0) {
                return null;
            }
        }
        File f = new File(root, path);
        return f.isFile() ? f : null;
    }

    private static String readLine(InputStream in) throws IOException {
        StringBuilder sb = new StringBuilder();
        int b;
        while (sb.length() < 8192) {
            b = in.read();
            if (b < 0) {
                return sb.length() == 0 ? null : sb.toString();
            }
            if (b == '\n') {
                return sb.toString();
            }
            if (b != '\r') {
                sb.append((char) b);
            }
        }
        return sb.toString();
    }

    private static void respond(OutputStream out, int code, String type, long length) throws IOException {
        String reason = code == 200 ? "OK" : code == 404 ? "Not Found" : "Not Implemented";
        String head = "HTTP/1.0 " + code + " " + reason + "\r\n"
                + "Content-Type: " + type + "\r\n"
                + "Connection: close\r\n";
        if (length >= 0) {
            head += "Content-Length: " + length + "\r\n";
        }
        head += "\r\n";
        out.write(head.getBytes("ISO-8859-1"));
        out.flush();
    }

    private static String mime(String name) {
        String p = name.toLowerCase();
        if (p.endsWith(".html") || p.endsWith(".htm")) return "text/html; charset=utf-8";
        if (p.endsWith(".js") || p.endsWith(".mjs")) return "application/javascript; charset=utf-8";
        if (p.endsWith(".json")) return "application/json; charset=utf-8";
        if (p.endsWith(".wasm")) return "application/wasm";
        if (p.endsWith(".css")) return "text/css; charset=utf-8";
        if (p.endsWith(".svg")) return "image/svg+xml; charset=utf-8";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".jpg") || p.endsWith(".jpeg") || p.endsWith(".jfif")) return "image/jpeg";
        if (p.endsWith(".webp")) return "image/webp";
        if (p.endsWith(".gif")) return "image/gif";
        if (p.endsWith(".ico")) return "image/x-icon";
        if (p.endsWith(".pdf")) return "application/pdf";
        if (p.endsWith(".woff2")) return "font/woff2";
        if (p.endsWith(".woff")) return "font/woff";
        if (p.endsWith(".ttf")) return "font/ttf";
        if (p.endsWith(".mp4")) return "video/mp4";
        if (p.endsWith(".mp3")) return "audio/mpeg";
        if (p.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
        if (p.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        if (p.endsWith(".txt")) return "text/plain; charset=utf-8";
        if (p.endsWith(".zip")) return "application/zip";
        return "application/octet-stream";
    }
}