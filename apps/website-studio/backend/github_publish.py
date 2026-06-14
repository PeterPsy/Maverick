"""GitHub pull-request publishing for Website Studio."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from publish_workflow import working_branch_for_site


HttpTransport = Callable[[str, str, dict[str, Any]], tuple[int, dict[str, Any] | list[Any] | bytes]]
GITHUB_API_BASE = "https://api.github.com"


class GitHubPublishConflict(ValueError):
    """Raised when Website Studio cannot update an existing PR branch without force."""


def publish_to_github_pull_request(
    *,
    source_root: Path,
    diff_files: list[dict[str, object]],
    site: dict[str, object],
    request: dict[str, object],
    connection: dict[str, object],
    token: str,
    transport: HttpTransport | None = None,
) -> dict[str, object]:
    owner = str(connection.get("owner") or "").strip()
    repo = str(connection.get("repo") or "").strip()
    base_branch = str(connection.get("base_branch") or "main").strip()
    branch = working_branch_for_site(site, request)
    http = transport or _default_github_transport

    base_ref = _github_request(http, "GET", f"/repos/{owner}/{repo}/git/ref/heads/{_quote_ref(base_branch)}", token=token)
    base_sha = str(((base_ref.get("object") or {}) if isinstance(base_ref, dict) else {}).get("sha") or "")
    if not base_sha:
        raise ValueError("GitHub base branch did not return a commit sha")
    base_commit = _github_request(http, "GET", f"/repos/{owner}/{repo}/git/commits/{base_sha}", token=token)
    base_tree_sha = str(((base_commit.get("tree") or {}) if isinstance(base_commit, dict) else {}).get("sha") or "")
    if not base_tree_sha:
        raise ValueError("GitHub base commit did not return a tree sha")

    tree_entries = _build_tree_entries(http, owner=owner, repo=repo, token=token, source_root=source_root, diff_files=diff_files)
    if not tree_entries:
        raise ValueError("GitHub publish requires at least one changed file")

    tree = _github_request(
        http,
        "POST",
        f"/repos/{owner}/{repo}/git/trees",
        token=token,
        body={"base_tree": base_tree_sha, "tree": tree_entries},
    )
    tree_sha = str(tree.get("sha") or "") if isinstance(tree, dict) else ""
    if not tree_sha:
        raise ValueError("GitHub did not return a tree sha")
    commit = _github_request(
        http,
        "POST",
        f"/repos/{owner}/{repo}/git/commits",
        token=token,
        body={
            "message": f"Website Studio publish {request['id']}",
            "tree": tree_sha,
            "parents": [base_sha],
        },
    )
    commit_sha = str(commit.get("sha") or "") if isinstance(commit, dict) else ""
    if not commit_sha:
        raise ValueError("GitHub did not return a commit sha")

    _upsert_working_branch(http, owner=owner, repo=repo, branch=branch, token=token, commit_sha=commit_sha)
    pull = _open_or_reuse_pull_request(
        http,
        owner=owner,
        repo=repo,
        branch=branch,
        base_branch=base_branch,
        token=token,
        site=site,
        request=request,
    )

    return {
        "provider": "github",
        "connection_id": str(connection.get("id") or ""),
        "owner": owner,
        "repo": repo,
        "base_branch": base_branch,
        "working_branch": branch,
        "publish_request_id": str(request.get("id") or ""),
        "commit_sha": commit_sha,
        "pull_request_number": pull.get("number") if isinstance(pull, dict) else None,
        "pull_request_url": str(pull.get("html_url") or "") if isinstance(pull, dict) else "",
        "status": "pull_request_open",
    }


def _build_tree_entries(
    http: HttpTransport,
    *,
    owner: str,
    repo: str,
    token: str,
    source_root: Path,
    diff_files: list[dict[str, object]],
) -> list[dict[str, object]]:
    tree_entries: list[dict[str, object]] = []
    for item in diff_files:
        rel_path = str(item.get("path") or "").strip()
        if not rel_path:
            continue
        status = str(item.get("status") or "").strip()
        if status == "deleted":
            tree_entries.append({"path": rel_path, "mode": "100644", "type": "blob", "sha": None})
            continue
        file_path = source_root / rel_path
        if not file_path.is_file():
            continue
        blob = _github_request(
            http,
            "POST",
            f"/repos/{owner}/{repo}/git/blobs",
            token=token,
            body={"content": b64encode(file_path.read_bytes()).decode("ascii"), "encoding": "base64"},
        )
        blob_sha = str(blob.get("sha") or "") if isinstance(blob, dict) else ""
        if not blob_sha:
            raise ValueError(f"GitHub did not return a blob sha for `{rel_path}`")
        tree_entries.append({"path": rel_path, "mode": "100644", "type": "blob", "sha": blob_sha})
    return tree_entries


def _upsert_working_branch(
    http: HttpTransport,
    *,
    owner: str,
    repo: str,
    branch: str,
    token: str,
    commit_sha: str,
) -> None:
    branch_ref_path = f"/repos/{owner}/{repo}/git/ref/heads/{_quote_ref(branch)}"
    existing_ref = _github_request(http, "GET", branch_ref_path, token=token, allow_status={200, 404})
    if isinstance(existing_ref, dict) and existing_ref.get("_status_code") == 404:
        _github_request(http, "POST", f"/repos/{owner}/{repo}/git/refs", token=token, body={"ref": f"refs/heads/{branch}", "sha": commit_sha})
        return
    existing_sha = str((((existing_ref or {}).get("object") or {}) if isinstance(existing_ref, dict) else {}).get("sha") or "")
    if existing_sha == commit_sha:
        return
    try:
        _github_request(http, "PATCH", branch_ref_path, token=token, body={"sha": commit_sha, "force": False})
    except ValueError as error:
        raise GitHubPublishConflict(
            "GitHub publish branch update was rejected without force; review the existing Website Studio branch or create a new publish request."
        ) from error


def _open_or_reuse_pull_request(
    http: HttpTransport,
    *,
    owner: str,
    repo: str,
    branch: str,
    base_branch: str,
    token: str,
    site: dict[str, object],
    request: dict[str, object],
) -> dict[str, Any]:
    existing_pulls = _github_request(
        http,
        "GET",
        f"/repos/{owner}/{repo}/pulls?{urlencode({'state': 'open', 'head': f'{owner}:{branch}', 'base': base_branch})}",
        token=token,
    )
    pull = existing_pulls[0] if isinstance(existing_pulls, list) and existing_pulls else None
    if isinstance(pull, dict):
        return pull
    created = _github_request(
        http,
        "POST",
        f"/repos/{owner}/{repo}/pulls",
        token=token,
        body={
            "title": f"Website Studio publish: {site.get('display_name') or site.get('slug') or site['id']}",
            "head": branch,
            "base": base_branch,
            "body": f"Automated Website Studio publish request `{request['id']}`.",
        },
    )
    return created if isinstance(created, dict) else {}


def _default_github_transport(method: str, url: str, request: dict[str, Any]) -> tuple[int, dict[str, Any] | list[Any] | bytes]:
    body = request.get("json")
    headers = dict(request.get("headers") or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as response:
            payload = response.read()
            return response.status, _decode_json_bytes(payload)
    except Exception as error:  # pragma: no cover - exercised by live runtime failures
        status_code = int(getattr(error, "code", 502) or 502)
        payload = getattr(error, "read", lambda: b"")()
        decoded = _decode_json_bytes(payload) if payload else {"message": str(error)}
        return status_code, decoded


def _github_request(
    transport: HttpTransport,
    method: str,
    path: str,
    *,
    token: str,
    body: dict[str, object] | None = None,
    allow_status: set[int] | None = None,
) -> dict[str, Any] | list[Any]:
    allowed = allow_status or {200, 201}
    status_code, payload = transport(
        method,
        f"{GITHUB_API_BASE}{path}",
        {
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "maverick-website-studio",
            },
            "json": body,
        },
    )
    if status_code not in allowed:
        detail = _github_error_detail(payload)
        raise ValueError(f"GitHub API request failed with status {status_code}: {detail}")
    if isinstance(payload, dict) and status_code not in {200, 201}:
        return {**payload, "_status_code": status_code}
    if isinstance(payload, (dict, list)):
        return payload
    return {}


def _decode_json_bytes(payload: bytes) -> dict[str, Any] | list[Any] | bytes:
    if not payload:
        return {}
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload
    return decoded if isinstance(decoded, (dict, list)) else {"value": decoded}


def _github_error_detail(payload: object) -> str:
    if isinstance(payload, dict):
        message = str(payload.get("message") or "request failed")
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            message = f"{message}; {len(errors)} validation error(s)"
        return _redact_secret_text(message)
    return "request failed"


def _redact_secret_text(value: str) -> str:
    text = re.sub(r"(https?://)([^/@:\s]+):([^/@\s]+)@", r"\1***:***@", value)
    return re.sub(r"(gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|Bearer\s+\S+)", "<redacted>", text)


def _quote_ref(value: str) -> str:
    return quote(value, safe="")
