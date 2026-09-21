"""GitHub Actions operations backed by a GitHub App installation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import io
import json
import re
import time
from typing import Any
from urllib import error, parse, request
import zipfile


DEFAULT_OWNER = "giuntiocram"
DEFAULT_REPO = "maverick-glasses-ios"
DEFAULT_REF = "maverick-integration"
DEFAULT_WORKFLOW = "ios-install-device.yml"
DEFAULT_DEVICE_ID = "00008120-00144CD90130201E"
DEFAULT_API_BASE = "https://api.github.com"

REQUIRED_SECRETS = ("github-app-id", "github-installation-id", "github-app-private-key")
SUPPORTED_ACTIONS = (
    "manifest",
    "dispatch",
    "dispatch_and_wait",
    "list_runs",
    "run_jobs",
    "run_status",
    "run_logs",
    "wait",
)


class GitHubActionsError(RuntimeError):
    """Raised when GitHub Actions operations cannot complete."""


@dataclass(frozen=True)
class GitHubAppCredentials:
    app_id: str
    installation_id: str
    private_key: str


def handle_action(arguments: dict[str, Any], *, app_secrets: dict[str, Any], app_secret_errors: list[Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "manifest").strip()
    if action not in SUPPORTED_ACTIONS:
        return {"ok": False, "error": "unsupported_action", "allowed_actions": list(SUPPORTED_ACTIONS)}
    if action == "manifest":
        return _manifest()

    if app_secret_errors:
        return {
            "ok": False,
            "error": "secret_delivery_failed",
            "detail": "Core Secrets could not deliver the GitHub App credentials.",
            "secret_errors": _redacted_secret_errors(app_secret_errors),
        }

    credentials = _credentials_from_secrets(app_secrets)
    client = GitHubActionsClient(credentials, api_base=str(arguments.get("api_base") or DEFAULT_API_BASE))

    if action == "dispatch":
        return client.dispatch(arguments)
    if action == "dispatch_and_wait":
        return client.dispatch_and_wait(arguments)
    if action == "list_runs":
        return client.list_runs(arguments)
    if action == "run_jobs":
        return client.run_jobs(arguments)
    if action == "run_status":
        return client.run_status(arguments)
    if action == "run_logs":
        return client.run_logs(arguments)
    if action == "wait":
        return client.wait(arguments)
    return {"ok": False, "error": "unsupported_action"}


class GitHubActionsClient:
    def __init__(self, credentials: GitHubAppCredentials, *, api_base: str = DEFAULT_API_BASE) -> None:
        self.credentials = credentials
        self.api_base = api_base.rstrip("/")
        self._installation_token: str | None = None

    def dispatch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        owner, repo = _repo(arguments)
        workflow_id = _workflow(arguments)
        ref = str(arguments.get("ref") or DEFAULT_REF)
        inputs = _workflow_inputs(arguments)
        before = _now()
        self._request(
            "POST",
            f"/repos/{owner}/{repo}/actions/workflows/{parse.quote(workflow_id, safe='')}/dispatches",
            body={"ref": ref, "inputs": inputs},
        )
        run = self._find_recent_dispatch_run(owner=owner, repo=repo, workflow_id=workflow_id, branch=ref, after=before)
        return {
            "ok": True,
            "action": "dispatch",
            "repository": f"{owner}/{repo}",
            "workflow_id": workflow_id,
            "ref": ref,
            "inputs": inputs,
            "run": _run_summary(run) if run else None,
            "detail": "Workflow dispatched. Run discovery may lag for a few seconds." if run is None else "Workflow dispatched.",
        }

    def dispatch_and_wait(self, arguments: dict[str, Any]) -> dict[str, Any]:
        dispatch_result = self.dispatch(arguments)
        run = dispatch_result.get("run")
        if not isinstance(run, dict) or not run.get("id"):
            owner, repo = _repo(arguments)
            workflow_id = _workflow(arguments)
            branch = str(arguments.get("ref") or DEFAULT_REF)
            found = self._wait_for_recent_run(owner=owner, repo=repo, workflow_id=workflow_id, branch=branch, timeout_seconds=60)
            if found:
                run = _run_summary(found)
        if not isinstance(run, dict) or not run.get("id"):
            return {**dispatch_result, "ok": False, "error": "run_not_found_after_dispatch"}
        wait_result = self.wait({**arguments, "run_id": run["id"]})
        return {"ok": wait_result.get("ok", False), "action": "dispatch_and_wait", "dispatch": dispatch_result, "run": wait_result.get("run")}

    def list_runs(self, arguments: dict[str, Any]) -> dict[str, Any]:
        owner, repo = _repo(arguments)
        workflow_id = _workflow(arguments)
        query = {
            "per_page": str(int(arguments.get("limit") or 10)),
        }
        if arguments.get("branch") or arguments.get("ref"):
            query["branch"] = str(arguments.get("branch") or arguments.get("ref"))
        if arguments.get("event"):
            query["event"] = str(arguments.get("event"))
        path = f"/repos/{owner}/{repo}/actions/workflows/{parse.quote(workflow_id, safe='')}/runs?{parse.urlencode(query)}"
        payload = self._request("GET", path)
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else []
        return {"ok": True, "action": "list_runs", "repository": f"{owner}/{repo}", "workflow_id": workflow_id, "runs": [_run_summary(run) for run in runs if isinstance(run, dict)]}

    def run_jobs(self, arguments: dict[str, Any]) -> dict[str, Any]:
        owner, repo = _repo(arguments)
        run_id = _required_int(arguments, "run_id")
        payload = self._request("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs?filter=all&per_page=100")
        jobs = payload.get("jobs") if isinstance(payload, dict) else []
        return {
            "ok": True,
            "action": "run_jobs",
            "repository": f"{owner}/{repo}",
            "run_id": run_id,
            "jobs": [_job_summary(job) for job in jobs if isinstance(job, dict)],
        }

    def run_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        owner, repo = _repo(arguments)
        run_id = _required_int(arguments, "run_id")
        payload = self._request("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}")
        return {"ok": True, "action": "run_status", "repository": f"{owner}/{repo}", "run": _run_summary(payload)}

    def wait(self, arguments: dict[str, Any]) -> dict[str, Any]:
        owner, repo = _repo(arguments)
        run_id = _required_int(arguments, "run_id")
        timeout_seconds = int(arguments.get("timeout_seconds") or 900)
        poll_seconds = max(2, int(arguments.get("poll_seconds") or 10))
        deadline = time.monotonic() + timeout_seconds
        last_run: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            payload = self._request("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}")
            last_run = payload if isinstance(payload, dict) else {}
            if str(last_run.get("status") or "") == "completed":
                break
            time.sleep(poll_seconds)
        if not last_run:
            last_run = self._request("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}")
        summary = _run_summary(last_run)
        return {"ok": summary.get("status") == "completed" and summary.get("conclusion") == "success", "action": "wait", "repository": f"{owner}/{repo}", "run": summary}

    def run_logs(self, arguments: dict[str, Any]) -> dict[str, Any]:
        owner, repo = _repo(arguments)
        run_id = _required_int(arguments, "run_id")
        max_bytes = int(arguments.get("max_bytes") or 20000)
        data = self._request_bytes("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs")
        files: list[dict[str, str]] = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in sorted(archive.namelist()):
                if name.endswith("/"):
                    continue
                text = archive.read(name).decode("utf-8", errors="replace")
                excerpt = _tail_text(text, max_bytes=max_bytes)
                files.append({"name": name, "excerpt": _redact_text(excerpt)})
        return {"ok": True, "action": "run_logs", "repository": f"{owner}/{repo}", "run_id": run_id, "files": files}

    def _wait_for_recent_run(self, *, owner: str, repo: str, workflow_id: str, branch: str, timeout_seconds: int) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_seconds
        after = _now() - timedelta(minutes=2)
        while time.monotonic() < deadline:
            run = self._find_recent_dispatch_run(owner=owner, repo=repo, workflow_id=workflow_id, branch=branch, after=after)
            if run:
                return run
            time.sleep(3)
        return None

    def _find_recent_dispatch_run(self, *, owner: str, repo: str, workflow_id: str, branch: str, after: datetime) -> dict[str, Any] | None:
        query = parse.urlencode({"branch": branch, "event": "workflow_dispatch", "per_page": "10"})
        path = f"/repos/{owner}/{repo}/actions/workflows/{parse.quote(workflow_id, safe='')}/runs?{query}"
        payload = self._request("GET", path)
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else []
        for run in runs if isinstance(runs, list) else []:
            if not isinstance(run, dict):
                continue
            created = _parse_github_time(str(run.get("created_at") or ""))
            if created and created >= after - timedelta(seconds=10):
                return run
        return None

    def _request(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> Any:
        data = self._request_bytes(method, path, body=body)
        if not data:
            return {}
        return json.loads(data.decode("utf-8"))

    def _request_bytes(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> bytes:
        url = f"{self.api_base}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Maverick-GitHub-Actions-App",
        }
        if "/app/installations/" in path and path.endswith("/access_tokens"):
            headers["Authorization"] = f"Bearer {self._app_jwt()}"
        else:
            headers["Authorization"] = f"Bearer {self._token()}"
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=payload, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=60) as response:
                return response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubActionsError(f"GitHub API {method} {path} failed with {exc.code}: {_redact_text(detail)}") from exc

    def _token(self) -> str:
        if self._installation_token:
            return self._installation_token
        payload = self._request(
            "POST",
            f"/app/installations/{parse.quote(self.credentials.installation_id, safe='')}/access_tokens",
        )
        token = str(payload.get("token") or "")
        if not token:
            raise GitHubActionsError("GitHub App installation token response did not include a token.")
        self._installation_token = token
        return token

    def _app_jwt(self) -> str:
        now = datetime.now(timezone.utc)
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iat": int((now - timedelta(seconds=60)).timestamp()),
            "exp": int((now + timedelta(minutes=9)).timestamp()),
            "iss": self.credentials.app_id,
        }
        signing_input = ".".join(
            [
                _base64url_json(header),
                _base64url_json(claims),
            ]
        ).encode("ascii")
        signature = _rsa_sha256_sign(self.credentials.private_key, signing_input)
        return signing_input.decode("ascii") + "." + _base64url(signature)


def _manifest() -> dict[str, Any]:
    return {
        "ok": True,
        "app_id": "github-actions",
        "default_repository": f"{DEFAULT_OWNER}/{DEFAULT_REPO}",
        "default_ref": DEFAULT_REF,
        "default_workflow": DEFAULT_WORKFLOW,
        "required_secrets": list(REQUIRED_SECRETS),
        "actions": list(SUPPORTED_ACTIONS),
    }


def reference_manifest() -> dict[str, Any]:
    return {"reference_manifest": {"entity_types": []}}


def _credentials_from_secrets(app_secrets: dict[str, Any]) -> GitHubAppCredentials:
    missing = [name for name in REQUIRED_SECRETS if not str(app_secrets.get(name) or "").strip()]
    if missing:
        raise GitHubActionsError(f"Missing delivered GitHub App secret(s): {', '.join(missing)}")
    private_key = _normalize_private_key(str(app_secrets["github-app-private-key"]))
    return GitHubAppCredentials(
        app_id=str(app_secrets["github-app-id"]).strip(),
        installation_id=_normalize_installation_id(str(app_secrets["github-installation-id"])),
        private_key=private_key,
    )


def _repo(arguments: dict[str, Any]) -> tuple[str, str]:
    repository = str(arguments.get("repository") or "").strip()
    if repository:
        if "/" not in repository:
            raise GitHubActionsError("repository must use owner/repo format.")
        owner, repo = repository.split("/", 1)
        return owner, repo
    return str(arguments.get("owner") or DEFAULT_OWNER), str(arguments.get("repo") or DEFAULT_REPO)


def _workflow(arguments: dict[str, Any]) -> str:
    return str(arguments.get("workflow_id") or arguments.get("workflow") or DEFAULT_WORKFLOW)


def _workflow_inputs(arguments: dict[str, Any]) -> dict[str, str]:
    raw = arguments.get("inputs")
    inputs = {str(key): str(value) for key, value in raw.items()} if isinstance(raw, dict) else {}
    if "device_id" not in inputs and arguments.get("device_id", DEFAULT_DEVICE_ID) is not None:
        inputs["device_id"] = str(arguments.get("device_id") or DEFAULT_DEVICE_ID)
    if "launch_app" not in inputs and arguments.get("launch_app") is not None:
        inputs["launch_app"] = "true" if arguments.get("launch_app") is True else str(arguments.get("launch_app"))
    inputs.setdefault("launch_app", "false")
    return inputs


def _required_int(arguments: dict[str, Any], key: str) -> int:
    value = arguments.get(key)
    if value is None:
        raise GitHubActionsError(f"{key} is required.")
    return int(value)


def _run_summary(run: Any) -> dict[str, Any]:
    if not isinstance(run, dict):
        return {}
    return {
        "id": run.get("id"),
        "name": run.get("name"),
        "display_title": run.get("display_title"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "event": run.get("event"),
        "head_branch": run.get("head_branch"),
        "head_sha": run.get("head_sha"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "html_url": run.get("html_url"),
    }


def _job_summary(job: Any) -> dict[str, Any]:
    if not isinstance(job, dict):
        return {}
    raw_labels = job.get("labels")
    labels = [str(label) for label in raw_labels] if isinstance(raw_labels, list) else []
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "status": job.get("status"),
        "conclusion": job.get("conclusion"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "runner_name": job.get("runner_name"),
        "runner_group_name": job.get("runner_group_name"),
        "labels": labels,
    }


def _redacted_secret_errors(errors: list[Any]) -> list[dict[str, Any]]:
    result = []
    for item in errors:
        if isinstance(item, dict):
            result.append({key: value for key, value in item.items() if key not in {"value", "raw_value", "secret_value"}})
        else:
            result.append({"error": str(item)})
    return result


def _redact_text(text: str) -> str:
    redacted = text
    for marker in ("ghp_", "github_pat_", "ghs_", "ghu_", "gho_", "ghr_"):
        redacted = redacted.replace(marker, f"{marker}<redacted>")
    return redacted


def _base64url_json(payload: dict[str, Any]) -> str:
    return _base64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _rsa_sha256_sign(private_key: str, signing_input: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception as error:
        raise GitHubActionsError("Python cryptography package is required to sign GitHub App JWTs.") from error

    try:
        key = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
        return key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception as error:
        raise GitHubActionsError("Could not sign GitHub App JWT with the delivered private key.") from error


def _normalize_private_key(value: str) -> str:
    text = value.strip().strip("\"'")
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    if "BEGIN " in text and "PRIVATE KEY" in text:
        return text
    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8", errors="strict").strip()
    except Exception:
        return text
    if "BEGIN " in decoded and "PRIVATE KEY" in decoded:
        return decoded
    return text


def _normalize_installation_id(value: str) -> str:
    text = value.strip().strip("\"'")
    if text.isdigit():
        return text
    match = re.search(r"(?:installations/|installation_id=)(\d+)", text)
    if match:
        return match.group(1)
    number_match = re.search(r"(\d{5,})", text)
    if number_match:
        return number_match.group(1)
    return text


def _tail_text(text: str, *, max_bytes: int) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    return encoded[-max_bytes:].decode("utf-8", errors="replace")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_github_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
