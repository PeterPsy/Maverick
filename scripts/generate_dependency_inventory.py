"""Generate a direct-dependency inventory for Maverick root and app packages."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _root_inventory(root: Path) -> dict:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [
        line.strip()
        for line in (root / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    package_json = _read_json(root / "package.json")
    optional_dependencies = pyproject["project"].get("optional-dependencies", {})
    return {
        "python": {
            "name": pyproject["project"]["name"],
            "version": pyproject["project"]["version"],
            "requires_python": pyproject["project"]["requires-python"],
            "runtime_dependencies": list(pyproject["project"].get("dependencies", [])),
            "optional_dependencies": {name: list(values) for name, values in sorted(optional_dependencies.items())},
            "dev_dependencies": list(optional_dependencies.get("dev", [])),
            "requirements_dev": requirements,
        },
        "node": {
            "name": package_json.get("name"),
            "version": package_json.get("version"),
            "scripts": package_json.get("scripts", {}),
        },
    }


def _app_inventory(app_root: Path) -> dict:
    package_json = _read_json(app_root / "package.json")
    package_lock = _read_json(app_root / "package-lock.json")
    root_package = package_lock.get("packages", {}).get("", {})
    return {
        "app_id": app_root.name,
        "package_name": package_json.get("name"),
        "version": package_json.get("version"),
        "private": bool(package_json.get("private", False)),
        "dependencies": dict(sorted((root_package.get("dependencies") or {}).items())),
        "dev_dependencies": dict(sorted((root_package.get("devDependencies") or {}).items())),
    }


def generate_inventory(root: Path) -> dict:
    apps_root = root / "apps"
    apps = [
        _app_inventory(app_root)
        for app_root in sorted(path for path in apps_root.iterdir() if path.is_dir() and (path / "package.json").is_file() and (path / "package-lock.json").is_file())
    ]
    return {
        "schema_version": "1",
        "generated_from": "repository_root",
        "root": _root_inventory(root),
        "apps": apps,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target = root / "docs" / "legal" / "third_party_inventory.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(generate_inventory(root), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
