"""Supply-chain identity and inventory checks for the pinned OpenDesign source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Callable


MANIFEST_SCHEMA_VERSION = "3"
PATCH_SCHEMA_VERSION = "1"
CERTIFICATION_SCHEMA_VERSION = "4"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SupplyChainError(RuntimeError):
    """Raised when pinned source or supply-chain evidence is inconsistent."""


def read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupplyChainError(f"cannot read {path.name} as strict JSON") from exc
    if not isinstance(payload, dict):
        raise SupplyChainError(f"{path.name} must contain an object")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SupplyChainError(f"cannot hash {path.name}") from exc
    return digest.hexdigest()


def validate_manifest(manifest: dict[str, object]) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise SupplyChainError("unsupported OpenDesign manifest schema")
    upstream = _mapping(manifest.get("upstream"), "upstream")
    _exact_text(upstream, "repository", "https://github.com/nexu-io/open-design.git")
    _exact_text(upstream, "tag", "open-design-v0.16.1")
    _exact_text(upstream, "commit", "276b4d8e970bc143d7ad060181a89a834e3d9caf")
    _exact_text(upstream, "release_version", "0.16.1")
    identity = _mapping(upstream.get("release_identity"), "upstream.release_identity")
    _exact_text(identity, "package_path", "apps/packaged/package.json")
    _exact_text(identity, "package_name", "@open-design/packaged")
    _exact_text(identity, "package_version", "0.16.1")
    _exact_text(upstream, "root_package_version", "0.15.1")
    toolchain = _mapping(manifest.get("toolchain"), "toolchain")
    _exact_text(toolchain, "node", "~24")
    _exact_text(toolchain, "package_manager", "pnpm@10.33.2")
    if manifest.get("patch_series") != "patches/series.json":
        raise SupplyChainError("patch series path is not pinned")
    certification = _mapping(manifest.get("certification"), "certification")
    if certification.get("separate_from_packaging") is not True:
        raise SupplyChainError("upstream certification must remain separate from packaging")
    build = _mapping(manifest.get("build"), "build")
    encoded_build = json.dumps(build, sort_keys=True)
    forbidden = ("--shard=", "--retry", "--testNamePattern", "checkpoint", "deferred_shards")
    if any(token in encoded_build for token in forbidden):
        raise SupplyChainError("normal packaging contains upstream certification orchestration")
    install = _string_list(build.get("install"), "build.install")
    if install != ["corepack", "pnpm", "install", "--frozen-lockfile"]:
        raise SupplyChainError("packaging must use the frozen lockfile")


def validate_patch_series(
    service_root: Path,
    manifest: dict[str, object],
    *,
    source_root: Path | None = None,
) -> dict[str, object]:
    series_path = _safe_child(service_root, str(manifest["patch_series"]))
    series = read_json(series_path)
    if series.get("schema_version") != PATCH_SCHEMA_VERSION:
        raise SupplyChainError("unsupported patch inventory schema")
    patches = series.get("patches")
    if not isinstance(patches, list) or not patches:
        raise SupplyChainError("patch inventory must not be empty")
    declared_files: set[str] = set()
    for item in patches:
        patch = _mapping(item, "patch")
        relative_patch = _safe_relative_text(patch.get("path"), "patch.path")
        patch_path = _safe_child(series_path.parent, relative_patch)
        _digest_matches(patch_path, patch.get("sha256"), "patch")
        if not isinstance(patch.get("reason"), str) or not str(patch["reason"]).strip():
            raise SupplyChainError("every patch requires a reason")
        files = patch.get("files")
        if not isinstance(files, list) or not files:
            raise SupplyChainError("every patch requires a file inventory")
        patch_files: set[str] = set()
        for file_item in files:
            entry = _mapping(file_item, "patch file")
            relative_file = _safe_relative_text(entry.get("path"), "patch file path")
            if relative_file in declared_files:
                raise SupplyChainError(f"duplicate patch file: {relative_file}")
            declared_files.add(relative_file)
            patch_files.add(relative_file)
            for field in ("pre_sha256", "post_sha256"):
                if not isinstance(entry.get(field), str) or not SHA256_RE.fullmatch(str(entry[field])):
                    raise SupplyChainError(f"invalid {field} for {relative_file}")
            if source_root is not None:
                _digest_matches(
                    _safe_child(source_root, relative_file),
                    entry["pre_sha256"],
                    f"upstream {relative_file}",
                )
        patch_headers = {
            match.group(1)
            for match in re.finditer(
                r"^diff --git a/([^ ]+) b/[^ ]+$",
                patch_path.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            )
        }
        if patch_headers != patch_files:
            raise SupplyChainError("patch headers do not match the declared file inventory")
    return series


def validate_certification_record(service_root: Path, manifest: dict[str, object]) -> dict[str, object]:
    certification = _mapping(manifest.get("certification"), "certification")
    record_path = _safe_child(
        service_root,
        _safe_relative_text(certification.get("record"), "certification.record"),
    )
    _digest_matches(record_path, certification.get("record_sha256"), "certification record")
    record = read_json(record_path)
    if record.get("schema_version") != CERTIFICATION_SCHEMA_VERSION:
        raise SupplyChainError("unsupported certification record schema")
    upstream = _mapping(record.get("upstream"), "certification upstream")
    manifest_upstream = _mapping(manifest.get("upstream"), "upstream")
    for field in ("repository", "tag", "commit"):
        if upstream.get(field) != manifest_upstream.get(field):
            raise SupplyChainError(f"certification {field} does not match the manifest")
    policy = _mapping(record.get("policy"), "certification policy")
    expected = {
        "separate_from_packaging": True,
        "source_tree": "exact_unpatched_upstream",
        "max_parallel_commands": 1,
        "max_test_workers": 1,
        "retry_count": 0,
        "allow_exclusions": False,
        "requires_frozen_lockfile": True,
    }
    if any(policy.get(key) != value for key, value in expected.items()):
        raise SupplyChainError("certification policy is not bounded and exclusion-free")
    commands = _mapping(record.get("commands"), "certification commands")
    encoded_commands = json.dumps(commands, sort_keys=True)
    forbidden = ("--shard=", "--retry", "--testNamePattern", "--exclude")
    if any(token in encoded_commands for token in forbidden):
        raise SupplyChainError("certification commands contain sharding, retry, or exclusions")
    for suite in ("web", "daemon"):
        command = _string_list(commands.get(suite), f"certification commands.{suite}")
        if "--maxWorkers=1" not in command:
            raise SupplyChainError(f"{suite} certification is not limited to one worker")
    latest = _mapping(record.get("latest_acceptance"), "latest_acceptance")
    if latest.get("status") not in {"pending_recertification", "passed", "completed_with_failures"}:
        raise SupplyChainError("unknown upstream acceptance status")
    return record


def validate_source_identity(
    source_root: Path,
    manifest: dict[str, object],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    source_root = Path(source_root)
    if source_root.is_symlink():
        raise SupplyChainError("upstream source must be a real directory")
    source_root = source_root.resolve(strict=True)
    if not source_root.is_dir():
        raise SupplyChainError("upstream source must be a real directory")
    upstream = _mapping(manifest.get("upstream"), "upstream")
    commit = str(upstream["commit"])
    tag = str(upstream["tag"])
    head = _git_output(run, source_root, "rev-parse", "HEAD")
    tag_commit = _git_output(run, source_root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if head != commit or tag_commit != commit:
        raise SupplyChainError("upstream HEAD or tag does not match the pinned commit")
    status = _git_output(run, source_root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise SupplyChainError("upstream tracked source is dirty")
    release_identity = _mapping(upstream.get("release_identity"), "release_identity")
    release_package = read_json(_safe_child(source_root, str(release_identity["package_path"])))
    root_package = read_json(_safe_child(source_root, "package.json"))
    if release_package.get("name") != release_identity.get("package_name"):
        raise SupplyChainError("release package name does not match")
    if release_package.get("version") != release_identity.get("package_version"):
        raise SupplyChainError("release package version does not match")
    if root_package.get("version") != upstream.get("root_package_version"):
        raise SupplyChainError("root package version does not match")
    if root_package.get("packageManager") != _mapping(manifest["toolchain"], "toolchain").get("package_manager"):
        raise SupplyChainError("package manager pin does not match upstream")


def _git_output(run: Callable[..., subprocess.CompletedProcess[str]], root: Path, *args: str) -> str:
    result = run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SupplyChainError(f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _safe_child(root: Path, relative: str) -> Path:
    relative_path = PurePosixPath(relative)
    if relative_path.is_absolute() or not relative_path.parts or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise SupplyChainError(f"unsafe relative path: {relative}")
    candidate = root.joinpath(*relative_path.parts)
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise SupplyChainError(f"path escapes its inventory root: {relative}") from exc
    return candidate


def _safe_relative_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise SupplyChainError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SupplyChainError(f"{field} is unsafe")
    return value


def _digest_matches(path: Path, expected: object, label: str) -> None:
    if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
        raise SupplyChainError(f"{label} has an invalid SHA-256")
    if sha256_file(path) != expected:
        raise SupplyChainError(f"{label} SHA-256 does not match")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SupplyChainError(f"{field} must be an object")
    return value


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise SupplyChainError(f"{field} must be a non-empty string list")
    return list(value)


def _exact_text(mapping: dict[str, object], field: str, expected: str) -> None:
    if mapping.get(field) != expected:
        raise SupplyChainError(f"{field} must equal {expected}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SupplyChainError(f"duplicate JSON field: {key}")
        result[key] = value
    return result
