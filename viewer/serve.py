#!/usr/bin/env python3
"""minimal local server to run the offline LiveMCQ viewer:
    python3 viewer/serve.py
then open http://localhost:8000/viewer/   (Ctrl+C to stop)

Differences from plain `python3 -m http.server`:
  * threaded, so a long video stream doesn't block the UI
  * HTTP Range (206) support — required for seeking inside <video>/<audio>
    and used by the bundled pdf.js for large handouts
  * explicit MIME types for .mjs / .wasm (pdf.js is an ES-module build;
    browsers refuse modules served as application/octet-stream)
"""
import http.server
import os
import re
import socketserver
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("LIVEMCQ_PORT", "8000"))

_EXTRA = {
    ".mjs": "application/javascript",
    ".js": "application/javascript",
    ".wasm": "application/wasm",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
    extensions_map.update(_EXTRA)
    extensions_map[""] = "application/octet-stream"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def send_head(self):
        self._range_left = None
        rng = self.headers.get("Range")
        if not rng or self.command != "GET":
            return super().send_head()
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None
        try:
            size = os.fstat(f.fileno()).st_size
            m = re.match(r"bytes=(\d*)-(\d*)\s*$", rng.strip())
            if not m or size == 0:
                f.close()
                return super().send_head()
            a, b = m.group(1), m.group(2)
            if a == "":
                start = max(0, size - int(b))
                end = size - 1
            else:
                start = int(a)
                end = int(b) if b else size - 1
            if end > size - 1:
                end = size - 1
            if start > end or start >= size:
                f.close()
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Last-Modified", self.date_time_string(os.fstat(f.fileno()).st_mtime))
            self.end_headers()
            f.seek(start)
            self._range_left = end - start + 1
            return f
        except Exception:
            f.close()
            raise

    def copyfile(self, source, outputfile):
        left = getattr(self, "_range_left", None)
        if left is None:
            return super().copyfile(source, outputfile)
        while left > 0:
            chunk = source.read(min(64 * 1024, left))
            if not chunk:
                break
            outputfile.write(chunk)
            left -= len(chunk)

    def log_message(self, fmt, *args):
        # keep the console readable during long video streams
        if "GET /viewer/" in (fmt % args) or " 4" in (fmt % args) or " 5" in (fmt % args):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


os.chdir(ROOT)
with Server(("0.0.0.0", PORT), RangeHandler) as httpd:
    print(f"\n  LiveMCQ offline archive →  http://localhost:{PORT}/viewer/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
