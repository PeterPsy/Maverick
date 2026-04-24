#!/usr/bin/env python3
"""Build source-buildable Maverick app frontends."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv in (["-h"], ["--help"]):
        print("usage: build_app_frontends.py")
        print()
        print("Build every app that declares lifecycle.rebuild=true.")
        return 0
    if argv:
        raise SystemExit(f"Unexpected arguments: {' '.join(argv)}")
    for app_root in _rebuildable_app_roots(REPOSITORY_ROOT / "apps"):
        print(f"==> Building frontend dependencies in {app_root}", flush=True)
        subprocess.run(["npm", "ci"], cwd=app_root, check=True)
        subprocess.run(["npm", "run", "build"], cwd=app_root, check=True)
    return 0


def _rebuildable_app_roots(apps_root: Path) -> list[Path]:
    roots: list[Path] = []
    for contract_path in sorted(apps_root.glob("*/app_contract.json")):
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
        lifecycle = payload.get("lifecycle") if isinstance(payload, dict) else None
        entrypoints = payload.get("entrypoints") if isinstance(payload, dict) else None
        frontend = entrypoints.get("frontend") if isinstance(entrypoints, dict) else None
        if not isinstance(lifecycle, dict) or lifecycle.get("rebuild") is not True or not isinstance(frontend, str):
            continue
        app_root = contract_path.parent
        package_path = app_root / "package.json"
        if not package_path.is_file():
            raise SystemExit(f"App `{app_root.name}` declares lifecycle.rebuild but has no package.json.")
        package_payload = json.loads(package_path.read_text(encoding="utf-8"))
        scripts = package_payload.get("scripts") if isinstance(package_payload, dict) else None
        build_script = str(scripts.get("build") or "").strip() if isinstance(scripts, dict) else ""
        if not build_script:
            raise SystemExit(f"App `{app_root.name}` declares lifecycle.rebuild but has no build script.")
        if _is_noop_build_script(build_script):
            raise SystemExit(f"App `{app_root.name}` declares lifecycle.rebuild with a no-op build script.")
        roots.append(app_root)
    return roots


def _is_noop_build_script(script: str) -> bool:
    normalized = script.replace(" ", "").replace("'", '"').lower()
    return "process.exit(0)" in normalized or "accesssync(\"frontend/dist/index.html\")" in normalized


if __name__ == "__main__":
    raise SystemExit(main())
