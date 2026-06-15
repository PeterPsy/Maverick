"""Create the curated OpenDesign bundle consumed by ``opendesign_launcher.py``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import subprocess
from typing import Callable


SERVICE_ROOT = Path(__file__).resolve().parent
APP_ROOT = SERVICE_ROOT.parent
MANIFEST_PATH = SERVICE_ROOT / "opendesign_bundle.json"
GENERATED_COPY_NAMES = {"node_modules", ".next", "dist", "__pycache__", ".turbo"}


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
    _adapt_curated_workspace(output)
    _write_bundle_metadata(output, manifest)
    if not args.skip_build:
        _run_build(output)
    _validate_output(output, manifest, built=not args.skip_build)
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
    package_json = json.loads((source / "package.json").read_text(encoding="utf-8"))
    expected_version = manifest["upstream"]["version"]
    if str(package_json.get("version") or "") != expected_version:
        raise SystemExit(f"OpenDesign package version is {package_json.get('version')!r}, expected {expected_version!r}.")
    expected_package_manager = manifest["bundle"]["package_manager"]
    if str(package_json.get("packageManager") or "") != expected_package_manager:
        raise SystemExit(
            f"OpenDesign package manager is {package_json.get('packageManager')!r}, expected {expected_package_manager!r}."
        )
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
            shutil.copytree(src, dst, ignore=_ignore_for_copy(source, excluded))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _is_excluded(relative: Path, excluded: set[Path]) -> bool:
    return any(relative == item or item in relative.parents for item in excluded)


def _ignore_for_copy(source_root: Path, excluded: set[Path]) -> Callable[[str, list[str]], set[str]]:
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        try:
            directory_relative = Path(directory).resolve().relative_to(source_root)
        except ValueError:
            directory_relative = Path()
        for name in names:
            candidate = directory_relative / name
            if name in GENERATED_COPY_NAMES or _is_excluded(candidate, excluded):
                ignored.add(name)
        return ignored

    return ignore


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


def _adapt_curated_workspace(output: Path) -> None:
    package_json_path = output / "package.json"
    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    scripts = package_json.get("scripts")
    if isinstance(scripts, dict):
        scripts.pop("postinstall", None)
    dev_dependencies = package_json.get("devDependencies")
    if isinstance(dev_dependencies, dict):
        for name in list(dev_dependencies):
            if name.startswith("@open-design/tools-"):
                dev_dependencies.pop(name, None)
    package_json_path.write_text(json.dumps(package_json, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    (output / "pnpm-workspace.yaml").write_text(
        "\n".join(
            [
                "packages:",
                "  - apps/daemon",
                "  - apps/web",
                "  - packages/*",
                "",
                "overrides:",
                "  brace-expansion: 5.0.6",
                "  devalue: 5.8.1",
                "  fast-uri: 3.1.2",
                "  hono: 4.12.19",
                "  ip-address: 10.2.0",
                "  postcss: 8.5.15",
                "  protobufjs: 8.4.0",
                "  qs: 6.15.2",
                "  tmp: 0.2.7",
                "  yaml: 2.9.0",
                "",
                "onlyBuiltDependencies:",
                "  - better-sqlite3",
                "  - core-js",
                "  - esbuild",
                "  - protobufjs",
                "  - sharp",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _run_build(output: Path) -> None:
    corepack = shutil.which("corepack")
    if corepack is None:
        raise SystemExit("corepack is required to install pnpm and build the OpenDesign bundle.")
    subprocess.run([corepack, "pnpm", "install", "--no-frozen-lockfile"], cwd=output, check=True)
    subprocess.run(
        [corepack, "pnpm", "-r", "--workspace-concurrency=4", "--if-present", "run", "build"],
        cwd=output,
        check=True,
    )


def _validate_output(output: Path, manifest: dict, *, built: bool) -> None:
    for relative_text in manifest["exclude_paths"]:
        if Path(relative_text).name in GENERATED_COPY_NAMES:
            continue
        if (output / relative_text).exists():
            raise SystemExit(f"Excluded OpenDesign path was copied into the bundle: {relative_text}")
    required_paths = ["package.json", "pnpm-lock.yaml", "apps/daemon/package.json", "apps/web/package.json"]
    if built:
        required_paths.extend(
            [
                manifest["bundle"]["built_entrypoint"],
                manifest["bundle"]["web_static_dir"],
            ]
        )
        required_paths.extend(
            f"{relative}/dist"
            for relative in manifest["include_paths"]
            if str(relative).startswith("packages/")
        )
    missing = [relative for relative in required_paths if not (output / relative).exists()]
    if missing:
        raise SystemExit(f"OpenDesign bundle is missing required paths: {', '.join(missing)}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
