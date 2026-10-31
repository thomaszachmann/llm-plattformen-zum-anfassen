"""Echo-Upstream: gibt die Header zurück, die beim Modellserver ankommen."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps({"seen": {k: v for k, v in self.headers.items()
                                    if k in ("Authorization", "X-Tenant")}})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", 11500), H).serve_forever()
