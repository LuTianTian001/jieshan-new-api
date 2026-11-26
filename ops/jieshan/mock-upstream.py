"""Two deterministic, offline replies for a private New API trial. No real models."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import time
from urllib.parse import urlsplit

MODEL = "jieshan-smoke"


class MockUpstream(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Do not log request URLs, headers or prompts.

    def reply(self, status, doc):
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def fail(self, status, message, kind="invalid_request_error"):
        self.reply(status, {"error": {"message": message, "type": kind, "code": kind}})

    def do_GET(self):
        if urlsplit(self.path).path != "/v1/models":
            return self.fail(404, "Unknown mock route")
        self.reply(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "local-test"}]})

    def do_POST(self):
        if urlsplit(self.path).path != "/v1/chat/completions":
            return self.fail(404, "Only chat/completions is simulated")
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                return self.fail(400, "Send a small JSON body")
            req = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            return self.fail(400, "Invalid JSON body")
        if not isinstance(req, dict) or req.get("model") != MODEL or req.get("stream"):
            return self.fail(400, "Use jieshan-smoke with stream=false")
        if self.server.mode == "limited":
            return self.fail(429, "Synthetic limit for failover testing", "rate_limit_exceeded")
        self.reply(200, {
            "id": "chatcmpl-jieshan-smoke", "object": "chat.completion", "created": int(time()), "model": MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "介山测试通了"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        })


if __name__ == "__main__":
    mode = os.environ.get("MOCK_MODE", "ok")
    if mode not in {"ok", "limited"}:
        raise SystemExit("MOCK_MODE must be ok or limited")
    with ThreadingHTTPServer((os.environ.get("MOCK_HOST", "0.0.0.0"), int(os.environ.get("MOCK_PORT", "8080"))), MockUpstream) as server:
        server.mode = mode
        print(f"{mode} mock ready on port {server.server_port}", flush=True)
        server.serve_forever()
