#!/usr/bin/env python3
"""Root-installed launcher for the isolated OpenDesign artifact authority."""

from __future__ import annotations

import json
import os
from pathlib import Path
import grp
import pwd
import re
import stat
import sys
from typing import Any


CONFIG_PATH = Path("/etc/maverick/opendesign-artifact-authority.json")
WORKSPACE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])$")
ALLOWED_OPERATIONS = frozenset({"verify", "repair", "provision", "gc", "publish-web"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def main() -> int:
    try:
        _root_protected_file(Path(__file__).absolute())
        config = _read_root_config(CONFIG_PATH)
        request = _read_request()
        os.chdir("/")
        _enter_authority_identity(config)
        result = _run_request(config, request)
    except Exception as error:
        payload = {
            "ok": False,
            "error_code": str(getattr(error, "code", type(error).__name__)),
            "phase": str(getattr(error, "phase", "artifact_authority")),
        }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 1
    print(
        json.dumps(
            {"ok": True, "result": result},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _read_root_config(path: Path) -> dict[str, Any]:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        raise RuntimeError("artifact authority config is not root-protected")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version",
        "authority_user",
        "authority_group",
        "module_root",
        "repository_root",
        "artifact_store_root",
        "artifact_source_root",
    }
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("schema_version") != "1":
        raise RuntimeError("artifact authority config is invalid")
    authority_user = payload.get("authority_user")
    authority_group = payload.get("authority_group")
    if not isinstance(authority_user, str) or not isinstance(authority_group, str):
        raise RuntimeError("artifact authority identity is invalid")
    try:
        account = pwd.getpwnam(authority_user)
        group = grp.getgrnam(authority_group)
    except KeyError as error:
        raise RuntimeError("artifact authority identity is unavailable") from error
    if account.pw_uid <= 0 or account.pw_gid != group.gr_gid:
        raise RuntimeError("artifact authority identity is invalid")
    for field in ("module_root", "repository_root", "artifact_store_root", "artifact_source_root"):
        value = payload.get(field)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise RuntimeError("artifact authority path is invalid")
    configured_module_root = Path(payload["module_root"])
    if configured_module_root.is_symlink():
        raise RuntimeError("artifact authority module snapshot cannot be a symlink")
    module_root = _root_protected_directory(configured_module_root)
    repository = Path(payload["repository_root"]).resolve(strict=True)
    store = Path(payload["artifact_store_root"]).resolve(strict=False)
    if store == repository or repository in store.parents:
        raise RuntimeError("artifact authority store is inside the repository")
    if repository.stat().st_uid == account.pw_uid:
        raise RuntimeError("artifact authority matches the repository owner")
    trusted_python_paths: list[str] = []
    for item in sys.path:
        if not item:
            continue
        candidate = Path(item)
        if not candidate.is_absolute():
            continue
        try:
            trusted_python_paths.append(str(_root_protected_directory(candidate)))
        except (OSError, RuntimeError):
            continue
    payload["module_root"] = str(module_root)
    payload["repository_root"] = str(repository)
    payload["artifact_store_root"] = str(store)
    artifact_source = Path(payload["artifact_source_root"])
    source_metadata = artifact_source.lstat()
    if stat.S_ISLNK(source_metadata.st_mode) or not stat.S_ISDIR(source_metadata.st_mode):
        raise RuntimeError("artifact authority source root is not a real directory")
    payload["artifact_source_root"] = str(artifact_source.resolve(strict=True))
    payload["authority_uid"] = account.pw_uid
    payload["authority_gid"] = group.gr_gid
    payload["trusted_python_paths"] = trusted_python_paths
    return payload


def _root_protected_directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    for candidate in (resolved, *resolved.parents):
        metadata = candidate.stat()
        if candidate == Path("/"):
            break
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise RuntimeError("artifact authority module snapshot is not root-protected")
    return resolved


def _root_protected_file(path: Path) -> Path:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        raise RuntimeError("artifact authority launcher is not root-protected")
    _root_protected_directory(path.parent)
    return path


def _read_request() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(16_385)
    if len(raw) > 16_384:
        raise RuntimeError("artifact authority request is too large")
    payload = json.loads(raw.decode("utf-8"))
    expected = {
        "schema_version",
        "operation",
        "workspace_id",
        "auto",
        "audit_workers",
        "candidate_path",
        "candidate_digest",
    }
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("schema_version") != "1":
        raise RuntimeError("artifact authority request is invalid")
    operation = payload.get("operation")
    workspace_id = payload.get("workspace_id")
    workers = payload.get("audit_workers")
    candidate_path = payload.get("candidate_path")
    candidate_digest = payload.get("candidate_digest")
    if operation not in ALLOWED_OPERATIONS:
        raise RuntimeError("artifact authority operation is not allowed")
    if not isinstance(workspace_id, str) or WORKSPACE_ID.fullmatch(workspace_id) is None:
        raise RuntimeError("artifact authority workspace is invalid")
    if not isinstance(payload.get("auto"), bool):
        raise RuntimeError("artifact authority auto flag is invalid")
    if workers is not None and (isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 32):
        raise RuntimeError("artifact authority worker limit is invalid")
    if operation == "publish-web":
        if (
            not isinstance(candidate_path, str)
            or not Path(candidate_path).is_absolute()
            or len(candidate_path) > 4096
            or "\x00" in candidate_path
            or not isinstance(candidate_digest, str)
            or SHA256.fullmatch(candidate_digest) is None
        ):
            raise RuntimeError("artifact authority submission is invalid")
    elif candidate_path is not None or candidate_digest is not None:
        raise RuntimeError("artifact authority request has unexpected submission data")
    return payload


def _enter_authority_identity(config: dict[str, Any]) -> None:
    uid = int(config["authority_uid"])
    gid = int(config["authority_gid"])
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    if os.geteuid() != uid or os.getegid() != gid:
        raise RuntimeError("artifact authority did not enter its isolated identity")


def _run_request(config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    module_root = Path(config["module_root"])
    service_root = module_root / "apps/design-studio/service"
    sys.path[:] = [str(module_root), str(service_root), *config["trusted_python_paths"]]
    os.environ.clear()
    os.environ.update(
        {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PYTHONSAFEPATH": "1",
            "MAVERICK_APP_ARTIFACT_STORE_ROOT": str(config["artifact_store_root"]),
            "MAVERICK_OPENDESIGN_ARTIFACT_SOURCE_ROOT": str(config["artifact_source_root"]),
        }
    )
    from opendesign_artifact_operations import run_artifact_operation

    repository = Path(config["repository_root"])
    workspace_id = str(request["workspace_id"])
    data_root = repository / "workspaces" / workspace_id / "data/design-studio"
    return run_artifact_operation(
        str(request["operation"]),
        data_root=data_root,
        workspace_id=workspace_id,
        repository_root=repository,
        auto=bool(request["auto"]),
        audit_workers=request["audit_workers"],
        candidate_path=(
            None if request["candidate_path"] is None else Path(str(request["candidate_path"]))
        ),
        candidate_digest=request["candidate_digest"],
        _authority=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
