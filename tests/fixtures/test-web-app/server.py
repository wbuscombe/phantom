"""Minimal test web server for Phantom integration tests.

A simple HTTP server with known routes and DOM structure for testing
the Web Runner's navigation, action execution, and screenshot capture.

Usage:
    python server.py [--port PORT]
"""

from __future__ import annotations

import argparse
import contextlib
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "public"


class TestHandler(SimpleHTTPRequestHandler):
    """Request handler with routing and API endpoints."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        routes: dict[str, str] = {
            "/": "index.html",
            "/dashboard": "index.html",
            "/settings": "settings.html",
            "/admin": "admin.html",
        }

        path = self.path.split("?")[0]
        if path in routes:
            self.path = "/" + routes[path]
        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/seed":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b""
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"status": "seeded", "data": json.loads(body) if body else {}}
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        # Suppress request logging during tests
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9753)
    args = parser.parse_args()

    server = HTTPServer(("localhost", args.port), TestHandler)
    print(f"Test server listening on http://localhost:{args.port}")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    server.server_close()


if __name__ == "__main__":
    main()
