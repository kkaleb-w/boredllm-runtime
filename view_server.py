"""Serve the live view and its snapshot on localhost, for a Cloudflare tunnel.

Read-only in both directions: it writes nothing to the run and the page cannot send
anything back. No inbound port is opened; the tunnel dials out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import snapshot as snap

VIEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "view")
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}


class Handler(BaseHTTPRequestHandler):
    run = None

    def log_message(self, *a):
        pass

    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("cache-control", "no-store")
        self.send_header("x-robots-tag", "noindex")
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode())

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/snapshot.json", "/api/snapshot"):
            rundir = Handler.run or snap.newest_run()
            if not rundir:
                return self._send(json.dumps({"error": "no runs yet"}), TYPES[".json"], 503)
            return self._send(json.dumps(snap.build(rundir)), TYPES[".json"])
        if path == "/health":
            return self._send(json.dumps({"ok": True, "run": Handler.run}), TYPES[".json"])
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(VIEW, rel))
        if not full.startswith(VIEW) or not os.path.isfile(full):
            return self._send("not found", "text/plain", 404)
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as fh:
            self._send(fh.read(), TYPES.get(ext, "application/octet-stream"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4180)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--run", default=None, help="run dir; default is the newest under ~/creature/runs")
    args = ap.parse_args()
    Handler.run = args.run
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"view on http://{args.host}:{args.port}  run={Handler.run or '(newest)'}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
