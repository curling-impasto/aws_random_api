# -----------------------------------------------------------------------------
# random/docker/app.py
#
# Tiny HTTP server — GET /random
#
# 80% of requests  ->  HTTP 200  {"status": "success", "message": "Hello from random!", "request_id": "<uuid>"}
# 20% of requests  ->  HTTP 500  {"status": "error",   "message": "Something went wrong.", "request_id": "<uuid>"}
#
# GET /health  -> HTTP 200  {"status": "healthy"}  (silent — not logged)
#   Used exclusively by the ALB health check so that health probes never
#   trigger the 80/20 business logic or pollute CloudWatch Logs.
#
# Every /random response is logged as a single JSON line to stdout.
# The ECS awslogs driver ships stdout lines to CloudWatch Logs as individual
# log events — filterable by the "status" field (e.g. status = "error").
#
# Stdlib only — no pip install needed.
# -----------------------------------------------------------------------------

import json
import logging
import random
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", force=True)


class RandomHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Health check — silent, no logging, always 200.
        # Configure the ALB target group health check to use this path so that
        # health probes never trigger the 80/20 business logic or write to logs.
        if self.path == "/health":
            body = json.dumps({"status": "healthy"}).encode("utf-8")
            self._respond(200, body)
            return

        if self.path != "/random":
            body = json.dumps({"status": "not_found", "path": self.path}).encode(
                "utf-8"
            )
            self._respond(404, body)
            return

        request_id = str(uuid.uuid4())

        # 80 / 20 split — random.random() returns [0.0, 1.0)
        if random.random() < 0.2:
            payload = {
                "status": "error",
                "message": "Something went wrong.",
                "request_id": request_id,
            }
            logging.error(json.dumps(payload))
            self._respond(500, json.dumps(payload).encode("utf-8"))
        else:
            payload = {
                "status": "success",
                "message": "Hello from random!",
                "request_id": request_id,
            }
            logging.info(json.dumps(payload))
            self._respond(200, json.dumps(payload).encode("utf-8"))

    def _respond(self, code, body_bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def log_message(self, format, *args):
        pass  # silence built-in access log — we emit structured JSON ourselves


def main():
    server = HTTPServer(("", PORT), RandomHandler)
    logging.info(json.dumps({"status": "starting", "port": PORT}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info(json.dumps({"status": "shutting_down"}))
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
