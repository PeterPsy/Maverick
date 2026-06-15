"""Create the curated OpenDesign bundle consumed by ``opendesign_launcher.py``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import subprocess


SERVICE_ROOT = Path(__file__).resolve().parent
APP_ROOT = SERVICE_ROOT.parent
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="OpenDesign checkout at the pinned tag.")
    parser.add_argument(
        "--output",
        default=str(SERVICE_ROOT / "vendor" / "open-design"),
        help="Bundle destination inside the Design Studio app source.",
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing output directory.")
    parser.add_argument("--skip-build", action="store_true", help="Copy sources without running pnpm install/build.")
    args = parser.parse_args()

    manifest = _read_manifest()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    _assert_inside_app(output)
    _validate_source(source, manifest)
    if output.exists():
        if not args.force:
            raise SystemExit(f"Output already exists: {output}. Use --force to replace it.")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    _copy_curated_paths(source, output, manifest)
    _write_bundle_metadata(output, manifest)
    if not args.skip_build:
        _run_build(output)
    print(json.dumps({"ok": True, "output": str(output), "built": not args.skip_build}, indent=2))


def _read_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _assert_inside_app(path: Path) -> None:
    root = APP_ROOT.resolve()
    if root != path and root not in path.parents:
        raise SystemExit("Bundle output must stay inside apps/design-studio.")


def _validate_source(source: Path, manifest: dict) -> None:
    if not (source / "package.json").is_file():
        raise SystemExit(f"OpenDesign source does not look valid: {source}")
    expected = manifest["upstream"]["commit"]
    actual = _git_commit(source)
    if actual and actual != expected:
        raise SystemExit(f"OpenDesign checkout is {actual}, expected {expected}.")


def _git_commit(source: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def _copy_curated_paths(source: Path, output: Path, manifest: dict) -> None:
    excluded = {Path(item) for item in manifest.get("exclude_paths", [])}
    for relative_text in manifest["include_paths"]:
        relative = Path(relative_text)
        if _is_excluded(relative, excluded):
            continue
        src = source / relative
        dst = output / relative
        if not src.exists():
            raise SystemExit(f"Manifest include path is missing from upstream checkout: {relative_text}")
        if src.is_dir():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, ignore=_ignore_for_copy)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _is_excluded(relative: Path, excluded: set[Path]) -> bool:
    return any(relative == item or item in relative.parents for item in excluded)


def _ignore_for_copy(_directory: str, names: list[str]) -> set[str]:
    ignored = {"node_modules", ".next/cache", "dist", "__pycache__", ".turbo"}
    return {name for name in names if name in ignored}


def _write_bundle_metadata(output: Path, manifest: dict) -> None:
    payload = {
        "schema_version": "1",
        "created_at": datetime.now(tz=UTC).isoformat(),
        "source": manifest["upstream"],
        "bundle": manifest["bundle"],
        "sandbox": manifest["sandbox"],
    }
    (output / "maverick-bundle.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _run_build(output: Path) -> None:
    corepack = shutil.which("corepack")
    if corepack is None:
        raise SystemExit("corepack is required to install pnpm and build the OpenDesign bundle.")
    subprocess.run([corepack, "pnpm", "install", "--frozen-lockfile"], cwd=output, check=True)
    subprocess.run([corepack, "pnpm", "--filter", "@open-design/web", "run", "build"], cwd=output, check=True)
    subprocess.run([corepack, "pnpm", "--filter", "@open-design/daemon", "run", "build"], cwd=output, check=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
