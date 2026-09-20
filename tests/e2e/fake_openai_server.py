"""A deterministic localhost-only OpenAI chat-completions boundary."""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOpenAIServer:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.active_requests = 0
        self.peak_active_requests = 0
        self.delay = 0.0
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.loads(raw)
                with owner._lock:
                    owner.active_requests += 1
                    owner.peak_active_requests = max(
                        owner.peak_active_requests, owner.active_requests
                    )
                    owner.requests.append({"body": body, "timestamp": time.monotonic()})
                try:
                    if owner.delay:
                        time.sleep(owner.delay)
                    prompt = "\n".join(
                        str(message.get("content", "")) for message in body.get("messages", [])
                    )
                    match = re.search(r"ROW_ID=([A-Za-z0-9_-]+)", prompt)
                    if "E2E_ROUTE_FIN" in prompt:
                        content = "FIN"
                    elif "E2E_ROUTE_LEGAL" in prompt:
                        content = "LEGAL"
                    elif "E2E_ROUND2" in prompt:
                        content = "REDUCED::" + prompt[-24:].replace("\n", " ")
                    elif "E2E_SUMMARY" in prompt:
                        content = "SUMMARY::" + prompt[-24:].replace("\n", " ")
                    elif match:
                        content = f"RESULT::{match.group(1)}"
                    else:
                        content = "MOCK_RESPONSE"
                    payload = {
                        "id": "chatcmpl-test",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "e2e-model",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    }
                    encoded = json.dumps(payload).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                finally:
                    with owner._lock:
                        owner.active_requests -= 1

            def log_message(self, *_args):
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()
