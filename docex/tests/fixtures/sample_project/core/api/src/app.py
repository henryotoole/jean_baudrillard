"""Trivial HTTP server for the sample fixture.

Serves ``GET /health`` returning ``{"version": "0.1.0"}``. No external
deps — uses the stdlib http.server only — to keep the fixture light.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


VERSION = "0.1.0"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server contract
        if self.path == "/health":
            body = json.dumps({"version": VERSION}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Quiet logs in the fixture container.
        return


def main() -> None:
    srv = HTTPServer(("0.0.0.0", 8080), _Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
