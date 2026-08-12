"""Pinned OpenDesign repository export, source validation, and patch application."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import tarfile
from typing import Any

from opendesign_archive import validated_archive_members
from opendesign_artifact import ArtifactError, sha256_file
from opendesign_process import BuildProcessError, run_command
from opendesign_supply_chain import read_json, validate_patch_series


class SourceError(RuntimeError):
    """Raised when the immutable source export or patch set is inconsistent."""


def validate_repository(repository: Path, manifest: dict[str, Any]) -> dict[str, str]:
    repository = Path(repository)
    if repository.is_symlink() or not repository.is_dir():
        raise SourceError("OpenDesign source repository must be a real directory")
    repository = repository.resolve(strict=True)
    upstream = manifest["upstream"]
    commit = upstream["commit"]
    tag = upstream["tag"]
    resolved_commit = _git(repository, "rev-parse", f"{commit}^{{commit}}")
    resolved_tag = _git(repository, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    object_type = _git(repository, "cat-file", "-t", f"refs/tags/{tag}")
    signature = _git(repository, "log", "-1", "--format=%G?", commit)
    if resolved_commit != commit or resolved_tag != commit:
        raise SourceError("OpenDesign tag and commit do not resolve to the reviewed pin")
    expected_tag = upstream["tag_metadata"]
    if object_type != expected_tag["object_type"]:
        raise SourceError("OpenDesign tag object type changed")
    if expected_tag["signature"] == "unavailable" and signature not in {"N", "E"}:
        raise SourceError("OpenDesign source signature metadata changed")
    return {
        "repository": upstream["repository"],
        "tag": tag,
        "commit": commit,
        "tag_object_type": object_type,
        "commit_signature": signature,
    }


def export_source(repository: Path, destination: Path, manifest: dict[str, Any]) -> dict[str, str]:
    evidence = validate_repository(repository, manifest)
    if destination.exists() or destination.is_symlink():
        raise SourceError("OpenDesign export destination must not already exist")
    destination.mkdir(parents=True)
    archive_path = destination.parent / f".{destination.name}.source.tar"
    if archive_path.exists() or archive_path.is_symlink():
        raise SourceError("OpenDesign source archive destination is not clean")
    try:
        run_command(
            [
                "git",
                f"--git-dir={repository.resolve(strict=True)}",
                "archive",
                "--format=tar",
                f"--output={archive_path}",
                manifest["upstream"]["commit"],
            ],
            cwd=repository.parent,
        )
        with tarfile.open(archive_path, mode="r:") as bundle:
            members = validated_archive_members(bundle)
            bundle.extractall(destination, members=members, filter="data")
    except (ArtifactError, BuildProcessError, OSError, tarfile.TarError) as exc:
        raise SourceError("cannot export the pinned OpenDesign source") from exc
    finally:
        archive_path.unlink(missing_ok=True)
    validate_exported_source(destination, manifest)
    return evidence


def validate_exported_source(source: Path, manifest: dict[str, Any]) -> None:
    if source.is_symlink() or not source.is_dir():
        raise SourceError("OpenDesign export must be a real directory")
    upstream = manifest["upstream"]
    identity = upstream["release_identity"]
    release_package = read_json(_safe_file(source, identity["package_path"]))
    root_package = read_json(_safe_file(source, "package.json"))
    if release_package.get("name") != identity["package_name"]:
        raise SourceError("OpenDesign release package name does not match")
    if release_package.get("version") != identity["package_version"]:
        raise SourceError("OpenDesign release package version does not match")
    if root_package.get("version") != upstream["root_package_version"]:
        raise SourceError("OpenDesign root package version does not match")
    if root_package.get("packageManager") != manifest["toolchain"]["package_manager"]:
        raise SourceError("OpenDesign package manager pin does not match")
    lockfile = _safe_file(source, "pnpm-lock.yaml")
    if lockfile.is_symlink() or not lockfile.is_file():
        raise SourceError("OpenDesign lockfile must be a real file")


def apply_patch_series(
    source: Path,
    service_root: Path,
    manifest: dict[str, Any],
    *,
    components: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    series = validate_patch_series(service_root, manifest, source_root=source)
    series_path = _safe_file(service_root, manifest["fallback_build"]["patch_series"])
    evidence: list[dict[str, Any]] = []
    for entry_value in series["patches"]:
        if not isinstance(entry_value, dict):
            raise SourceError("OpenDesign patch entry is invalid")
        entry = entry_value
        component = str(entry["component"])
        if components is not None and component not in components:
            continue
        patch_path = _safe_file(series_path.parent, entry["path"])
        patch_command = [
            "patch",
            "--batch",
            "--forward",
            "--strip=1",
            f"--directory={source.resolve(strict=True)}",
            f"--input={patch_path}",
        ]
        run_command([*patch_command, "--dry-run"], cwd=source.parent)
        run_command(patch_command, cwd=source.parent)
        declared_files: list[str] = []
        for file_value in entry["files"]:
            if not isinstance(file_value, dict):
                raise SourceError("OpenDesign patch file entry is invalid")
            relative = file_value["path"]
            path = _safe_file(source, relative)
            if path.is_symlink() or not path.is_file():
                raise SourceError(f"OpenDesign patched file is missing: {relative}")
            if sha256_file(path) != file_value["post_sha256"]:
                raise SourceError(f"OpenDesign patch post-image mismatch: {relative}")
            declared_files.append(relative)
        evidence.append(
            {
                "path": entry["path"],
                "component": component,
                "sha256": entry["sha256"],
                "reason": entry["reason"],
                "files": sorted(declared_files),
            }
        )
    return evidence


def _git(repository: Path, *arguments: str) -> str:
    try:
        result = run_command(
            ["git", f"--git-dir={repository}", *arguments],
            cwd=repository.parent,
            capture=True,
        )
    except BuildProcessError as exc:
        raise SourceError(f"git {' '.join(arguments)} failed") from exc
    return result.stdout


def _safe_file(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SourceError(f"unsafe OpenDesign source path: {relative}")
    candidate = root.joinpath(*path.parts)
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise SourceError(f"OpenDesign source path escapes its root: {relative}") from exc
    return candidate
