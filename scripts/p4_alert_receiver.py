"""Local-only P4 webhook receiver that validates HMAC without logging payloads."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx


def signing_key() -> bytes:
    root = Path("/run/p4-runtime")
    with httpx.Client(base_url=os.getenv("VAULT_ADDR", "http://vault:8200"), timeout=5) as client:
        auth = client.post("/v1/auth/approle/login", json={
            "role_id": (root / "vault_role_id").read_text(encoding="utf-8").strip(),
            "secret_id": (root / "vault_secret_id").read_text(encoding="utf-8").strip(),
        })
        auth.raise_for_status()
        token = auth.json()["auth"]["client_token"]
        value = client.get(
            "/v1/preprod-kv/data/chatbi/webhook",
            params={"version": 1},
            headers={"X-Vault-Token": token},
        )
        value.raise_for_status()
        return value.json()["data"]["data"]["signing_key"].encode()


KEY = signing_key()
SEEN: set[str] = set()


class Handler(BaseHTTPRequestHandler):
    server_version = "P4AlertReceiver/1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_error(404)
            return
        self._json(200, {"status": "ok", "payload_logging": False})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/webhook":
            self.send_error(404)
            return
        length = min(int(self.headers.get("Content-Length", "0")), 16384)
        body = self.rfile.read(length)
        expected = "sha256=" + hmac.new(KEY, body, hashlib.sha256).hexdigest()
        supplied = self.headers.get("X-P4-Signature", "")
        key = self.headers.get("X-P4-Idempotency-Key", "")
        try:
            payload = json.loads(body)
            safe_schema = set(payload) == {
                "schema_version", "alert_id", "rule_code", "severity", "status",
                "environment", "data_classification", "trace_hash",
            }
        except (json.JSONDecodeError, TypeError):
            safe_schema = False
        if not hmac.compare_digest(expected, supplied) or not key or not safe_schema:
            self._json(401, {"accepted": False})
            return
        replay = key in SEEN
        SEEN.add(key)
        self._json(200, {"accepted": True, "idempotent_replay": replay})

    def log_message(self, format: str, *args) -> None:
        return

    def _json(self, status: int, value: dict) -> None:
        encoded = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
