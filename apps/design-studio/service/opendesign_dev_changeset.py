"""Immutable changeset resolution and materialization for Design Studio dev apply."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any, Iterable


PATCH_SERIES_PATH = "apps/design-studio/service/patches/series.json"


class DevApplyError(RuntimeError):
    """Raised when an incremental apply action fails."""

    def __init__(self, message: str, *, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class ChangeSet:
    source: str
    changed_files: tuple[str, ...]
    base_sha: str | None
    head_sha: str | None
    path_sha256: dict[str, str | None]


def resolve_changeset(arguments: dict[str, Any], *, repo_root: Path) -> ChangeSet:
    """Resolve one explicit changeset and freeze its declared path bytes."""
    explicit = arguments.get("changed_files")
    has_explicit = explicit is not None
    has_range = arguments.get("base_sha") is not None or arguments.get("head_sha") is not None
    if has_explicit == has_range:
        raise DevApplyError(
            "provide exactly one changeset: changed_files or base_sha with head_sha",
            report={},
        )
    if has_explicit:
        if not isinstance(explicit, list) or not explicit or not all(isinstance(item, str) for item in explicit):
            raise DevApplyError(
                "changed_files must be a non-empty array of repository-relative paths",
                report={},
            )
        changed = validated_changed_files(explicit)
        base_sha = None
        head_sha = None
        source = "explicit_paths"
    else:
        if not isinstance(arguments.get("base_sha"), str) or not isinstance(arguments.get("head_sha"), str):
            raise DevApplyError("base_sha and head_sha must be provided together", report={})
        base_sha = resolve_commit(repo_root, str(arguments["base_sha"]))
        head_sha = resolve_commit(repo_root, str(arguments["head_sha"]))
        current_head = resolve_commit(repo_root, "HEAD")
        if current_head != head_sha:
            raise DevApplyError("head_sha must resolve to the current checkout HEAD", report={})
        completed = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACDMRTUXB", base_sha, head_sha],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        changed = validated_changed_files(completed.stdout.splitlines())
        if not changed:
            raise DevApplyError("the selected commit range contains no changed files", report={})
        _assert_paths_match_commit(repo_root, changed, head_sha=head_sha)
        source = "git_range"
    snapshot = snapshot_paths(repo_root, changed)
    return ChangeSet(source, changed, base_sha, head_sha, snapshot)


@contextmanager
def materialize_changeset(repo_root: Path, changeset: ChangeSet):
    """Yield a committed source snapshot overlaid only with the declared explicit paths."""
    revision = changeset.head_sha or "HEAD"
    completed = subprocess.run(
        ["git", "archive", "--format=tar", revision],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise DevApplyError("could not materialize the changeset base tree", report={})
    with tempfile.TemporaryDirectory(prefix="mav-od-apply-") as temporary:
        snapshot_root = Path(temporary) / "repository"
        snapshot_root.mkdir()
        try:
            with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
                archive.extractall(snapshot_root, filter="data")
        except (tarfile.TarError, OSError) as error:
            raise DevApplyError("changeset base tree archive is invalid", report={}) from error
        if changeset.source == "explicit_paths":
            _overlay_explicit_paths(repo_root, snapshot_root, changeset.changed_files)
        observed = snapshot_paths(snapshot_root, changeset.changed_files)
        if observed != changeset.path_sha256:
            raise DevApplyError("materialized changeset bytes do not match the frozen snapshot", report={})
        _materialize_operational_inputs(repo_root, snapshot_root)
        yield snapshot_root


def changed_patch_series_components(
    changeset: ChangeSet,
    *,
    repo_root: Path,
) -> tuple[str, ...] | None:
    """Return patch components whose reviewed series entries changed semantically."""
    if PATCH_SERIES_PATH not in changeset.changed_files:
        return None
    before_revision = changeset.base_sha or "HEAD"
    after_revision = changeset.head_sha
    try:
        before = _read_json_at_revision(repo_root, before_revision, PATCH_SERIES_PATH)
        after = (
            _read_json_at_revision(repo_root, after_revision, PATCH_SERIES_PATH)
            if after_revision is not None
            else json.loads((repo_root / PATCH_SERIES_PATH).read_text(encoding="utf-8"))
        )
        return tuple(sorted(_semantic_patch_series_changes(before, after)))
    except (DevApplyError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return ("unknown",)


def assert_changeset_unchanged(changeset: ChangeSet, *, repo_root: Path) -> None:
    observed = snapshot_paths(repo_root, changeset.changed_files)
    if observed != changeset.path_sha256:
        raise DevApplyError("changeset bytes changed while dev apply was running", report={})


def resolve_commit(repo_root: Path, revision: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise DevApplyError("base_sha/head_sha must resolve to Git commits", report={})
    return value


def normalize_path(path: str) -> str:
    value = str(path).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def validated_changed_files(paths: Iterable[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for raw in paths:
        value = normalize_path(raw)
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
            raise DevApplyError(f"unsafe changed path: {raw}", report={})
        normalized.add(candidate.as_posix())
    if not normalized:
        raise DevApplyError("changeset contains no changed files", report={})
    return tuple(sorted(normalized))


def snapshot_paths(repo_root: Path, paths: tuple[str, ...]) -> dict[str, str | None]:
    snapshot: dict[str, str | None] = {}
    for relative in paths:
        path = repo_root / relative
        if path.is_symlink() or path.is_dir():
            raise DevApplyError(f"changed path must be a file or a deleted path: {relative}", report={})
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return snapshot


def _overlay_explicit_paths(repo_root: Path, snapshot_root: Path, paths: tuple[str, ...]) -> None:
    for relative in paths:
        source = repo_root / relative
        destination = _safe_snapshot_destination(snapshot_root, relative)
        if source.is_file() and not source.is_symlink():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        elif not source.exists() and not source.is_symlink():
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
        else:
            raise DevApplyError(
                f"changed path must be a real file or deletion: {relative}",
                report={},
            )


def _safe_snapshot_destination(snapshot_root: Path, relative: str) -> Path:
    destination = snapshot_root / relative
    cursor = snapshot_root
    for part in PurePosixPath(relative).parts[:-1]:
        cursor /= part
        if cursor.is_symlink():
            raise DevApplyError(f"snapshot path traverses a symlink: {relative}", report={})
    try:
        destination.resolve(strict=False).relative_to(snapshot_root.resolve())
    except ValueError as error:
        raise DevApplyError(f"snapshot path escapes the isolated checkout: {relative}", report={}) from error
    return destination


def _materialize_operational_inputs(repo_root: Path, snapshot_root: Path) -> None:
    node_modules = repo_root / "apps/design-studio/node_modules"
    snapshot_node_modules = snapshot_root / "apps/design-studio/node_modules"
    if node_modules.is_dir() and not node_modules.is_symlink() and not snapshot_node_modules.exists():
        before = _directory_content_sha256(node_modules)
        shutil.copytree(node_modules, snapshot_node_modules, symlinks=True)
        after = _directory_content_sha256(node_modules)
        copied = _directory_content_sha256(snapshot_node_modules)
        if before != after or copied != before:
            raise DevApplyError("Node dependency inputs changed during snapshot materialization", report={})

    vendor = repo_root / "apps/design-studio/service/vendor"
    snapshot_vendor = snapshot_root / "apps/design-studio/service/vendor"
    if vendor.is_dir() and not vendor.is_symlink() and not snapshot_vendor.exists():
        snapshot_vendor.parent.mkdir(parents=True, exist_ok=True)
        snapshot_vendor.symlink_to(vendor.resolve(), target_is_directory=True)


def _directory_content_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"link\0")
            digest.update(path.readlink().as_posix().encode("utf-8"))
        elif path.is_dir():
            digest.update(b"directory")
        elif path.is_file():
            digest.update(b"file\0")
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            raise DevApplyError("Node dependency snapshot contains an unsupported file type", report={})
        digest.update(b"\0")
    return digest.hexdigest()


def _read_json_at_revision(repo_root: Path, revision: str, relative: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise DevApplyError("patch series revision is unavailable", report={})
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("patch series must be an object")
    return value


def _semantic_patch_series_changes(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    if {key: value for key, value in before.items() if key != "patches"} != {
        key: value for key, value in after.items() if key != "patches"
    }:
        return {"unknown"}

    def entries(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        patches = payload.get("patches")
        if not isinstance(patches, list):
            raise ValueError("patch series patches must be an array")
        result: dict[str, dict[str, Any]] = {}
        for entry in patches:
            if not isinstance(entry, dict) or not isinstance(entry.get("component"), str):
                raise ValueError("patch series entry is invalid")
            component = str(entry["component"])
            if component in result:
                raise ValueError("patch series components must be unique")
            result[component] = entry
        return result

    before_entries = entries(before)
    after_entries = entries(after)
    return {
        component
        for component in set(before_entries) | set(after_entries)
        if before_entries.get(component) != after_entries.get(component)
    }


def _assert_paths_match_commit(repo_root: Path, paths: tuple[str, ...], *, head_sha: str) -> None:
    for relative in paths:
        completed = subprocess.run(
            ["git", "cat-file", "-e", f"{head_sha}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        path = repo_root / relative
        if completed.returncode != 0:
            if path.exists() or path.is_symlink():
                raise DevApplyError(f"changed path does not match head_sha: {relative}", report={})
            continue
        expected = subprocess.run(
            ["git", "show", f"{head_sha}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        ).stdout
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise DevApplyError(f"changed path does not match head_sha: {relative}", report={})
