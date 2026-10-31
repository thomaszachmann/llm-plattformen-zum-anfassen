"""Fake-Modellserver mit OpenAI-kompatibler API – nur fürs Labor (Tag 3/4)."""

import json
import os
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("FAKE_HOST", "127.0.0.1")
PORT = int(os.environ.get("FAKE_PORT", "11434"))
TOKEN_DELAY = float(os.environ.get("FAKE_TOKEN_DELAY", "0.05"))  # s pro Token
ERROR_RATE = float(os.environ.get("FAKE_ERROR_RATE", "0"))  # Anteil 503


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # Keep-Alive wie bei echten Modellservern

    def reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/v1/models":
            self.reply(200, {"object": "list", "data": [{"id": "mistral"}]})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        print(
            f"fake: tenant={self.headers.get('X-Tenant')} "
            f"auth={self.headers.get('Authorization')}",
            flush=True,
        )
        if self.path != "/v1/chat/completions":
            return self.reply(404, {"error": "not found"})
        if random.random() < ERROR_RATE:
            return self.reply(503, {"error": "fake overload"})
        n = int(req.get("max_tokens") or 16)
        time.sleep(n * TOKEN_DELAY)  # Generierungszeit ~ Anzahl Tokens
        prompt = req["messages"][-1]["content"]
        p = len(prompt.split())
        self.reply(
            200,
            {
                "id": f"fake-{random.randrange(10**6)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": req.get("model", "mistral"),
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": f"[fake] {prompt}"},
                    }
                ],
                "usage": {
                    "prompt_tokens": p,
                    "completion_tokens": n,
                    "total_tokens": p + n,
                },
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        pass  # Zugriffslog aus, die print-Zeile oben reicht


if __name__ == "__main__":
    print(f"fake llm on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
