"""Detached worker for post-cutover persistence cleanup."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from core.api.control_store import (
    ControlStoreSettings,
    build_control_plane_collections,
    control_plane_collection_specs,
)


def run_pending_cleanup_plans(*, repository_root: Path, active_settings: ControlStoreSettings) -> list[dict[str, Any]]:
    """Run pending cleanup plans whose target adapter is now active."""
    plan_root = repository_root / ".maverick" / "persistence-cleanup"
    if not plan_root.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for plan_path in sorted(plan_root.glob("*.json")):
        if plan_path.name.endswith((".done.json", ".failed.json")):
            continue
        if plan_path.with_suffix(".done.json").exists() or plan_path.with_suffix(".failed.json").exists():
            continue
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            target = _settings_from_plan(plan["target_adapter"])
            if not _same_adapter(active_settings, target):
                continue
            _clear_source_storage(plan)
            done_path = plan_path.with_suffix(".done.json")
            done_path.write_text(
                json.dumps({"status": "completed", "plan": str(plan_path), "mode": "startup"}, indent=2) + "\n",
                encoding="utf-8",
            )
            done_path.chmod(0o600)
            results.append({"status": "completed", "plan": str(plan_path)})
        except Exception as exc:
            failed_path = plan_path.with_suffix(".failed.json")
            failed_path.write_text(
                json.dumps({"status": "failed", "plan": str(plan_path), "error": str(exc)}, indent=2) + "\n",
                encoding="utf-8",
            )
            failed_path.chmod(0o600)
            results.append({"status": "failed", "plan": str(plan_path), "error": str(exc)})
    return results


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 1:
        print("usage: python -m core.api.persistence_cleanup_worker <plan.json>", file=sys.stderr)
        return 2
    plan_path = Path(args[0])
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        _wait_for_cutover(plan)
        _clear_source_storage(plan)
        plan_path.with_suffix(".done.json").write_text(
            json.dumps({"status": "completed", "plan": str(plan_path)}, indent=2) + "\n",
            encoding="utf-8",
        )
        plan_path.with_suffix(".done.json").chmod(0o600)
        return 0
    except Exception as exc:
        plan_path.with_suffix(".failed.json").write_text(
            json.dumps({"status": "failed", "plan": str(plan_path), "error": str(exc)}, indent=2) + "\n",
            encoding="utf-8",
        )
        plan_path.with_suffix(".failed.json").chmod(0o600)
        return 1


def _wait_for_cutover(plan: dict[str, Any]) -> None:
    previous_pid = int(plan.get("previous_pid") or 0)
    service_name = str(plan.get("service_name") or "maverick-core.service")
    health_url = str(plan.get("health_url") or "http://127.0.0.1:8014/health")
    deadline = time.monotonic() + float(plan.get("timeout_seconds") or 120.0)
    while time.monotonic() < deadline:
        current_pid = _service_main_pid(service_name)
        if previous_pid and current_pid == previous_pid:
            time.sleep(1)
            continue
        if _health_ok(health_url):
            return
        time.sleep(1)
    raise RuntimeError("Backend did not complete persistence cutover before cleanup timeout.")


def _clear_source_storage(plan: dict[str, Any]) -> None:
    repository_root = Path(str(plan["repository_root"]))
    source = _settings_from_plan(plan["source_adapter"])
    target = _settings_from_plan(plan["target_adapter"])
    if _same_adapter(source, target):
        raise RuntimeError("Refusing to clear source storage because source and target adapters match.")
    collections = build_control_plane_collections(source)
    for spec in control_plane_collection_specs(collections):
        replace_all = getattr(spec.collection, "replace_all", None)
        if replace_all is None:
            raise RuntimeError(f"Source collection `{spec.name}` does not support full replacement.")
        replace_all([])
    if source.kind == "json":
        _delete_json_root(repository_root=repository_root, json_root=source.json_root)


def _settings_from_plan(payload: dict[str, Any]) -> ControlStoreSettings:
    return ControlStoreSettings(
        kind=str(payload["kind"]),
        json_root=Path(str(payload["json_root"])),
        mongo_uri=payload.get("mongo_uri"),
        mongo_database=str(payload.get("mongo_database") or "maverick"),
        mongo_username=payload.get("mongo_username"),
        mongo_password_ref=payload.get("mongo_password_ref"),
    )


def _delete_json_root(*, repository_root: Path, json_root: Path) -> None:
    resolved_root = repository_root.resolve(strict=False)
    resolved_json_root = json_root.resolve(strict=False)
    try:
        resolved_json_root.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to delete JSON control store outside repository: {json_root}") from exc
    if resolved_json_root == resolved_root:
        raise RuntimeError("Refusing to delete repository root as JSON control store.")
    if json_root.exists():
        shutil.rmtree(json_root)


def _same_adapter(left: ControlStoreSettings, right: ControlStoreSettings) -> bool:
    if left.kind != right.kind:
        return False
    if left.kind == "json":
        return _same_path(left.json_root, right.json_root)
    return left.mongo_uri == right.mongo_uri and left.mongo_database == right.mongo_database


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        return str(left) == str(right)


def _service_main_pid(service_name: str) -> int | None:
    response = subprocess.run(
        ["systemctl", "show", service_name, "-p", "MainPID"],
        capture_output=True,
        text=True,
        check=False,
    )
    if response.returncode != 0:
        return None
    raw_value = response.stdout.strip().partition("=")[2]
    try:
        pid = int(raw_value)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _health_ok(url: str) -> bool:
    try:
        with urlopen(url, timeout=2.0) as response:
            return 200 <= response.status < 300
    except (OSError, TimeoutError, URLError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
