#!/usr/bin/env python3
"""Build source-buildable Maverick app frontends."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.shared.node_runtime import NODE_RUNTIME_REQUIREMENT, require_supported_node_runtime  # noqa: E402



def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv in (["-h"], ["--help"]):
        print("usage: build_app_frontends.py")
        print()
        print("Build every app with a declared frontend entrypoint.")
        return 0
    if argv:
        raise SystemExit(f"Unexpected arguments: {' '.join(argv)}")
    try:
        require_supported_node_runtime()
    except RuntimeError as exc:
        raise SystemExit(f"Building app frontends requires {NODE_RUNTIME_REQUIREMENT}: {exc}") from exc
    for build_root in _frontend_app_build_roots(REPOSITORY_ROOT / "apps"):
        print(f"==> Building frontend dependencies in {build_root}", flush=True)
        subprocess.run(["npm", "ci"], cwd=build_root, check=True)
        subprocess.run(["npm", "run", "build"], cwd=build_root, check=True)
    return 0


def _frontend_app_build_roots(apps_root: Path) -> list[Path]:
    roots: list[Path] = []
    for contract_path in sorted(apps_root.glob("*/app_contract.json")):
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
        entrypoints = payload.get("entrypoints") if isinstance(payload, dict) else None
        frontend = entrypoints.get("frontend") if isinstance(entrypoints, dict) else None
        if not isinstance(frontend, str):
            continue
        app_root = contract_path.parent
        package_root = _frontend_package_root(app_root=app_root, frontend_mount=frontend)
        package_path = package_root / "package.json"
        if not package_path.is_file():
            raise SystemExit(f"Frontend app `{app_root.name}` has no package.json.")
        package_payload = json.loads(package_path.read_text(encoding="utf-8"))
        scripts = package_payload.get("scripts") if isinstance(package_payload, dict) else None
        build_script = str(scripts.get("build") or "").strip() if isinstance(scripts, dict) else ""
        if not build_script:
            raise SystemExit(f"Frontend app `{app_root.name}` has no build script.")
        if _is_noop_build_script(build_script):
            raise SystemExit(f"Frontend app `{app_root.name}` has a no-op build script.")
        roots.append(package_root)
    return roots


def _frontend_package_root(*, app_root: Path, frontend_mount: str) -> Path:
    frontend_source_root = app_root / frontend_mount.split("/", 1)[0]
    if (frontend_source_root / "package.json").is_file():
        return frontend_source_root
    return app_root


def _is_noop_build_script(script: str) -> bool:
    normalized = script.replace(" ", "").replace("'", '"').lower()
    return "process.exit(0)" in normalized or "accesssync(\"frontend/dist/index.html\")" in normalized


if __name__ == "__main__":
    raise SystemExit(main())
