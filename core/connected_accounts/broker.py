"""Invocation-scoped private provider proxy; Google tokens never leave Core."""

import base64
from dataclasses import replace
from datetime import UTC, datetime
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import socketserver
import tempfile
from threading import Lock, Thread
import time
from urllib.request import Request

from core.connected_accounts import google
from core.connected_accounts.app_context import account_context, account_payload
from core.secrets.errors import SecretError
from core.apps.errors import AppHostingError

MAX_WIRE_BYTES = 60 * 1024 * 1024
REQUEST_HEADERS = {"accept", "content-type", "range", "if-match", "if-none-match", "content-range", "x-upload-content-type", "x-upload-content-length"}
RESPONSE_HEADERS = {"content-type", "content-length", "content-range", "range", "etag", "location", "retry-after"}


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(30)
        raw = self.rfile.readline(MAX_WIRE_BYTES + 1)
        if len(raw) > MAX_WIRE_BYTES or not raw.endswith(b"\n"):
            return
        result = self.server.broker.handle_request(raw)
        self.wfile.write(json.dumps(result, separators=(",", ":")).encode() + b"\n")


class AccountBroker:
    def __init__(self, *, context, identity_store, workspace_store, secret_store, app_store,
                 permissions, user_id, workspace_id, app_id, data_root, timeout_seconds=30,
                 sender=None):
        self.context = context
        self.identity_store, self.workspace_store = identity_store, workspace_store
        self.secret_store, self.app_store = secret_store, app_store
        self.scope = dict(permissions=permissions, user_id=user_id, workspace_id=workspace_id, app_id=app_id, data_root=data_root)
        self.sender = sender or google.provider_request
        self.deadline = time.monotonic() + max(30, timeout_seconds)
        self.capability = secrets.token_urlsafe(32)
        self.server = self.thread = self.root = None
        self.lock = Lock()
        self.closed = False
        self.token = None
        self.token_until = 0.0
        self.token_version = None
        self.request_count = 0

    def start(self):
        if not self.context or self.context["account"].status != "connected" or not self.context["services"]:
            return None
        self.root = Path(tempfile.mkdtemp(prefix="maverick-account-"))
        os.chmod(self.root, 0o700)
        path = self.root / "broker.sock"
        self.server = _Server(str(path), _Handler)
        self.server.broker = self
        os.chmod(path, 0o600)
        self.thread = Thread(target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True, name="account-broker")
        self.thread.start()
        descriptor = json.dumps({"socket": str(path), "capability": self.capability}, separators=(",", ":"))
        return "maverick-account:" + base64.urlsafe_b64encode(descriptor.encode()).decode()

    def handle_request(self, raw):
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or not hmac.compare_digest(str(request.get("capability") or ""), self.capability):
                raise google.AccountError("account_capability_invalid", status=403)
            with self.lock:
                if self.closed or time.monotonic() >= self.deadline or self.request_count >= 2000:
                    raise google.AccountError("account_capability_expired", status=403)
                self.request_count += 1
            context = account_context(identity_store=self.identity_store, workspace_store=self.workspace_store, **self.scope)
            if (context is None or context["account"].account_id != self.context["account"].account_id
                    or context["account"].status != "connected"):
                raise google.AccountError("account_access_revoked", status=403)
            account = context["account"]
            if not account.secret_ref or self.secret_store.get_secret(account.secret_ref.rsplit("/", 1)[-1]).status != "active":
                raise google.AccountError("account_credential_revoked", status=403)
            if self.app_store is not None:
                binding = self.app_store.get_workspace_app_binding(workspace_id=self.scope["workspace_id"], app_id=self.scope["app_id"])
                if binding.status != "enabled":
                    raise google.AccountError("account_app_disabled", status=403)
            method, url = str(request.get("method") or "GET"), str(request.get("url") or "")
            if not google.allowed_api_request(context["services"], method, url):
                raise google.AccountError("account_api_not_allowed", status=403)
            body = base64.b64decode(request.get("body_base64") or "", validate=True)
            if len(body) > google.MAX_RESPONSE_BYTES:
                raise google.AccountError("account_request_too_large", status=413)
            raw_headers = request.get("headers") or {}
            if not isinstance(raw_headers, dict):
                raise google.AccountError("account_request_invalid")
            headers = {key: str(value) for key, value in raw_headers.items() if str(key).lower() in REQUEST_HEADERS}
            headers["Authorization"] = "Bearer " + self._access_token(context["account"])
            status, returned_headers, data = self.sender(Request(url, data=body if body else None, headers=headers, method=method))
            return {"ok": True, "status": status, "headers": {key: value for key, value in returned_headers.items() if key.lower() in RESPONSE_HEADERS},
                    "body_base64": base64.b64encode(data).decode()}
        except (google.AccountError, SecretError, AppHostingError, ValueError, TypeError, KeyError) as error:
            return {"ok": False, "status": getattr(error, "status", 403), "error": getattr(error, "code", "account_request_denied")}

    def _access_token(self, account):
        with self.lock:
            version = (account.secret_ref, account.updated_at)
            if self.token and self.token_version == version and time.monotonic() < self.token_until:
                return self.token
            client_id, client_secret = google.credentials(self.secret_store)
            if not account.secret_ref:
                raise google.AccountError("google_reconnect_required", status=401)
            try:
                payload = google.json_request(google.TOKEN_URL, data={"client_id": client_id, "client_secret": client_secret,
                    "refresh_token": google.secret_value(self.secret_store, account.secret_ref), "grant_type": "refresh_token"})
            except google.AccountError as error:
                if error.code == "google_reconnect_required":
                    self.identity_store.account_store.save_account(replace(account, status="reconnect_required", updated_at=datetime.now(UTC)))
                raise
            if not isinstance(payload.get("access_token"), str) or not payload["access_token"]:
                raise google.AccountError("google_invalid_response", status=502)
            self.token = payload["access_token"]
            self.token_version = version
            self.token_until = time.monotonic() + max(0, float(payload.get("expires_in", 0)) - 60)
            return self.token

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.capability = ""
            self.token = None
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)
        if self.root:
            shutil.rmtree(self.root)


class AccountInvocation:
    """Attach private account state and broker authority to one app process."""

    def __init__(self, *, identity_store, workspace_store, secret_store, app_store,
                 binding, parsed, actor_user_id, payload, timeout_seconds):
        self.context = account_context(identity_store=identity_store, workspace_store=workspace_store,
            permissions=parsed.contract.permissions, user_id=actor_user_id,
            workspace_id=binding.workspace_id, app_id=binding.app_id, data_root=binding.data_root)
        self.broker = AccountBroker(context=self.context, identity_store=identity_store,
            workspace_store=workspace_store, secret_store=secret_store, app_store=app_store,
            permissions=parsed.contract.permissions, user_id=actor_user_id,
            workspace_id=binding.workspace_id, app_id=binding.app_id,
            data_root=binding.data_root, timeout_seconds=timeout_seconds)
        self.payload = dict(payload)

    def start(self):
        if self.context:
            self.payload["data_root"] = self.context["data_root"]
            replaced = set(self.context["replaces_secrets"])
            self.payload["app_secrets"] = {
                name: value for name, value in self.payload.get("app_secrets", {}).items()
                if name not in replaced
            }
            accounts = account_payload(self.context)
            handle = self.broker.start()
            if handle:
                accounts[0]["access_handle"] = handle
            self.payload["external_accounts"] = accounts
        return self.payload

    def close(self):
        self.broker.close()
