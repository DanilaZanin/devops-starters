"""Tiny demo service: two pure functions and a /health endpoint."""

import http.server
import json
import os


def add(a: int, b: int) -> int:
    return a + b


def is_palindrome(s: str) -> bool:
    normalized = s.lower().replace(" ", "")
    return normalized == normalized[::-1]


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            status, body = 200, {"status": "ok"}
        else:
            status, body = 404, {"error": "not found"}
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        print(format % args, flush=True)


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
