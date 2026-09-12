"""Local HTTP server with Range support and optional per-connection rate limit.

Used together with benchmark.py to demonstrate the speedup of segmented downloads.
"""

from __future__ import annotations

import http.server
import os
import socketserver
import sys
import time


class _Handler(http.server.BaseHTTPRequestHandler):
    # Injected from outside
    file_path: str = ""
    file_size: int = 0
    per_conn_limit_bps: int = 0   # bytes per second per connection; 0 = unlimited

    def do_HEAD(self):                                  # noqa: N802
        if self.path != "/file.bin":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(self.file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):                                  # noqa: N802
        if self.path != "/file.bin":
            self.send_error(404)
            return

        rng = self.headers.get("Range")
        start, end = 0, self.file_size - 1
        status = 200
        if rng and rng.startswith("bytes="):
            try:
                spec = rng[len("bytes="):]
                if "," in spec:
                    # Simplified: multi-range not supported
                    self.send_error(416)
                    return
                s, e = spec.split("-", 1)
                start = int(s) if s else 0
                end = int(e) if e else self.file_size - 1
                if start > end or start >= self.file_size:
                    self.send_error(416)
                    return
                end = min(end, self.file_size - 1)
                status = 206
            except ValueError:
                self.send_error(400)
                return

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{self.file_size}")
        self.send_header("Connection", "close")
        self.end_headers()

        chunk = 64 * 1024
        per_byte_delay = 0.0
        if self.per_conn_limit_bps > 0:
            per_byte_delay = 1.0 / self.per_conn_limit_bps

        with open(self.file_path, "rb") as f:
            f.seek(start)
            remaining = length
            buf = bytearray(chunk)
            while remaining > 0:
                n = f.readinto(buf)
                if not n:
                    break
                to_send = n if n <= remaining else remaining
                try:
                    self.wfile.write(buf[:to_send])
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= to_send
                if per_byte_delay > 0:
                    time.sleep(per_byte_delay * to_send)

    def log_message(self, *_args, **_kw):
        pass                              # silent


def serve(file_path: str, port: int, per_conn_kbps: int):
    _Handler.file_path = file_path
    _Handler.file_size = os.path.getsize(file_path)
    _Handler.per_conn_limit_bps = per_conn_kbps * 1024 if per_conn_kbps > 0 else 0

    class _TS(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    httpd = _TS(("127.0.0.1", port), _Handler)
    print(f"[server] listening on http://127.0.0.1:{port}/file.bin  "
          f"size={_Handler.file_size/1024/1024:.1f} MB  "
          f"per-conn-limit={per_conn_kbps} KB/s")
    httpd.serve_forever()


def _make_big_file(path: str, size_mb: int) -> None:
    """Generate a sparse test file with pseudo-random content."""
    with open(path, "wb") as f:
        for i in range(size_mb):
            # 1024 bytes of pseudo-random data, repeated 1024 times to fill 1 MB
            f.write(bytes((i * 7 + 13) & 0xFF for _ in range(1024)) * 1024)
            f.flush()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    kbps = int(sys.argv[2]) if len(sys.argv) > 2 else 0          # per-connection limit in KB/s
    size_mb = int(sys.argv[3]) if len(sys.argv) > 3 else 80     # test file size in MB

    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "big.bin")
    if not os.path.exists(tmp) or os.path.getsize(tmp) < size_mb * 1024 * 1024:
        print(f"[gen] creating {size_mb} MB test file -> {tmp}")
        _make_big_file(tmp, size_mb)

    serve(tmp, port, kbps)