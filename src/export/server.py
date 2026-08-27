"""Tiny stdlib static file server for the mobile snapshot.

Serves files from data/export/ (mainly snapshot.json.gz) over the network with:

- CORS headers (`Access-Control-Allow-Origin: *`) so the WebView app can fetch
  it cross-origin.
- Optional token auth: set env `GESTOR_API_TOKEN` to require
  `Authorization: Bearer <token>`.

Use over HTTPS (Tailscale certs / Caddy reverse proxy) when exposing the PC
to the internet. Do NOT expose this on the public internet without auth+HTTPS.
"""

import http.server
import json
import os
import socketserver
import sys
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
EXPORT_DIR = BASE_DIR / "data" / "export"
WEB_DIR = BASE_DIR / "app" / "web"

SERVE_WEB = False

INDEX_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Economy snapshot</title></head>
<body style="font-family: system-ui, sans-serif; padding: 2rem">
  <h1>Economy snapshot server</h1>
  <p>Mobile app data endpoint. The app fetches <a href="/snapshot.json">/snapshot.json</a>
     (gzip transparently decoded). Raw file: <a href="/snapshot.json.gz">snapshot.json.gz</a>.</p>
  <p><a href="/healthz">/healthz</a> (health check)</p>
</body>
</html>
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(EXPORT_DIR), **kwargs)

    def translate_path(self, path):
        # Serve snapshot endpoints from data/export/ and (optionally) the web
        # dashboard from app/web/.
        if SERVE_WEB and not urllib.parse.urlparse(path).path.startswith("/snapshot"):
            self.directory = str(WEB_DIR)
        else:
            self.directory = str(EXPORT_DIR)
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _authorized(self) -> bool:
        token = os.environ.get("GESTOR_API_TOKEN")
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {token}"

    def _write_json(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authorized():
            self._write_json(401, {"error": "unauthorized"})
            return

        path = urllib.parse.urlparse(self.path).path

        if path == "/healthz":
            self._write_json(200, {"status": "ok"})
            return

        if path in ("/snapshot", "/snapshot.json"):
            gz = EXPORT_DIR / "snapshot.json.gz"
            if not gz.exists():
                self._write_json(404, {"error": "no snapshot yet. run: main.py --export"})
                return
            body = gz.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if not SERVE_WEB and path in ("/", "/index.html"):
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        super().do_GET()

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    import argparse

    global SERVE_WEB

    parser = argparse.ArgumentParser(description="Serve the mobile snapshot (and optionally the web app) over HTTP")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--web", action="store_true", help="Also serve the web dashboard at /")
    args = parser.parse_args()
    SERVE_WEB = args.web

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Serving snapshot {EXPORT_DIR} on http://{args.host}:{args.port}")
    if SERVE_WEB:
        print(f"Web dashboard: http://{args.host}:{args.port}/ (from {WEB_DIR})")
    if os.environ.get("GESTOR_API_TOKEN"):
        print("Token auth: ENABLED (Authorization: Bearer <token>)")
    else:
        print("Token auth: DISABLED")

    with ThreadingHTTPServer((args.host, args.port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
