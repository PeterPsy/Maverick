"""Copy-on-write workspace effects for hosted shell and managed processes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat

from core.runtime.confined_filesystem import (
    MAX_CONFINED_LIST_ENTRIES,
    MAX_CONFINED_PATH_COMPONENTS,
    ConfinedWorkspaceFilesystem,
    FilesystemMutationGuard,
)
from core.runtime.confined_filesystem_batch import (
    ConfinedTextBatchWrite,
    write_confined_text_batch,
)
from core.runtime.confined_filesystem_metadata import (
    ConfinedPathMetadata,
    preserved_metadata_matches,
)
from core.runtime.hosted_workspace_effect_support import (
    MAX_HOSTED_EFFECT_FILES,
    MAX_HOSTED_EFFECT_FILE_BYTES,
    MAX_HOSTED_EFFECT_TOTAL_BYTES,
    create_hosted_effect_overlay_directories,
    scan_hosted_effect_overlay_upper,
)
from core.runtime.tool_errors import RuntimeToolError
from core.runtime.tool_full_workspace_support import (
    MutationInstructionGuard,
    prepare_mutation_instruction_guard,
)


@dataclass(frozen=True)
class HostedWorkspaceMutationScope:
    """One caller-observed instruction scope eligible for overlay commit."""

    path: str
    instruction_scope_digest: str


@dataclass(frozen=True)
class _BaselineFile:
    resource_identity: str
    resource_revision: str


@dataclass(frozen=True)
class _ChangedFile:
    path: str
    content: str
    baseline: _BaselineFile | None
    guard: MutationInstructionGuard
    create_mode: int
    create_uid: int
    create_gid: int
    target_atime_ns: int
    target_mtime_ns: int


class HostedWorkspaceEffectOverlay:
    """Keep arbitrary command writes private until a governed text diff commits."""

    def __init__(
        self,
        *,
        filesystem: ConfinedWorkspaceFilesystem,
        workspace_root: Path,
        scopes: tuple[HostedWorkspaceMutationScope, ...],
        scope_guards: tuple[MutationInstructionGuard, ...],
        baseline: dict[str, _BaselineFile],
        root: Path,
        upper: Path,
        work: Path,
        upper_baseline_metadata: ConfinedPathMetadata,
    ) -> None:
        self.filesystem = filesystem
        self.workspace_root = workspace_root
        self.scopes = scopes
        self.scope_guards = scope_guards
        self.baseline = baseline
        self.root = root
        self.upper = upper
        self.work = work
        self.transaction = root / "transaction"
        self.upper_baseline_metadata = upper_baseline_metadata
        self._closed = False
        self._recovery_required = False
        self._prepared_changes: tuple[_ChangedFile, ...] | None = None
        self._prepared_evidence: dict[str, object] | None = None

    @classmethod
    def create(
        cls,
        filesystem: ConfinedWorkspaceFilesystem,
        *,
        workspace_root: Path,
        runtime_root: Path,
        scopes: tuple[HostedWorkspaceMutationScope, ...],
    ) -> "HostedWorkspaceEffectOverlay":
        if not scopes:
            raise RuntimeToolError("workspace_mutation_scopes_invalid")
        guards: list[MutationInstructionGuard] = []
        baseline: dict[str, _BaselineFile] = {}
        for scope in scopes:
            if not filesystem.path_is_directory(scope.path):
                raise RuntimeToolError("workspace_mutation_scope_not_directory")
            guards.append(
                prepare_mutation_instruction_guard(
                    filesystem,
                    workspace_root=workspace_root,
                    path=scope.path,
                    expected_digest=scope.instruction_scope_digest,
                    target_is_directory=True,
                )
            )
            snapshot = filesystem.list_entries(
                scope.path,
                max_depth=MAX_CONFINED_PATH_COMPONENTS,
                page_size=MAX_CONFINED_LIST_ENTRIES,
            )
            if snapshot.payload.get("next_cursor") is not None:
                raise RuntimeToolError("workspace_effect_snapshot_too_large")
            for item in snapshot.payload.get("entries", ()):
                if not isinstance(item, dict) or item.get("type") != "file":
                    continue
                path = str(item.get("path") or "")
                identity = str(item.get("resource_identity") or "")
                revision = str(item.get("resource_revision") or "")
                if not path or not identity or not revision:
                    raise RuntimeToolError("workspace_effect_snapshot_invalid")
                candidate = _BaselineFile(identity, revision)
                previous = baseline.get(path)
                if previous is not None and previous != candidate:
                    raise RuntimeToolError("workspace_effect_snapshot_changed")
                baseline[path] = candidate
        root, upper, work, upper_baseline_metadata = (
            create_hosted_effect_overlay_directories(
                filesystem,
                runtime_root=runtime_root,
            )
        )
        return cls(
            filesystem=filesystem,
            workspace_root=workspace_root,
            scopes=scopes,
            scope_guards=tuple(guards),
            baseline=baseline,
            root=root,
            upper=upper,
            work=work,
            upper_baseline_metadata=upper_baseline_metadata,
        )

    def verify_before_spawn(self) -> None:
        for guard in self.scope_guards:
            guard.verify_before()

    def preview_commit(self) -> dict[str, object]:
        """Validate the private diff and return its exact intended public evidence."""
        if self._closed:
            raise RuntimeToolError("workspace_effect_overlay_closed")
        changed = self._validated_changes()
        evidence = self._effect_evidence(changed)
        self._prepared_changes = changed
        self._prepared_evidence = dict(evidence)
        return evidence

    def commit(
        self,
        *,
        expected_evidence: dict[str, object] | None = None,
        result_authority_guard: FilesystemMutationGuard | None = None,
    ) -> dict[str, object]:
        """Validate the complete upper diff before crossing any effect boundary."""
        if self._closed:
            raise RuntimeToolError("workspace_effect_overlay_closed")
        try:
            if expected_evidence is not None:
                if (
                    self._prepared_changes is None
                    or self._prepared_evidence != expected_evidence
                ):
                    raise RuntimeToolError("workspace_effect_snapshot_changed")
                changed = self._prepared_changes
                evidence = dict(self._prepared_evidence)
            else:
                changed = self._validated_changes()
                evidence = self._effect_evidence(changed)
            if expected_evidence is not None and evidence != expected_evidence:
                raise RuntimeToolError("workspace_effect_snapshot_changed")
            write_confined_text_batch(
                self.filesystem,
                tuple(
                    ConfinedTextBatchWrite(
                        path=item.path,
                        content=item.content,
                        expected_resource_identity=(
                            None
                            if item.baseline is None
                            else item.baseline.resource_identity
                        ),
                        expected_resource_revision=(
                            None
                            if item.baseline is None
                            else item.baseline.resource_revision
                        ),
                        mutation_guard=item.guard,
                        create_mode=item.create_mode,
                        create_uid=item.create_uid,
                        create_gid=item.create_gid,
                        target_atime_ns=item.target_atime_ns,
                        target_mtime_ns=item.target_mtime_ns,
                    )
                    for item in changed
                ),
                transaction_directory=self.transaction,
                commit_guard=result_authority_guard,
            )
            return evidence
        except RuntimeToolError as error:
            if error.reason_code == "tool_execution_unknown":
                self._recovery_required = True
            raise
        finally:
            self.discard()

    def _effect_evidence(
        self,
        changed: tuple[_ChangedFile, ...],
    ) -> dict[str, object]:
        paths = tuple(item.path for item in changed)
        return {
            "workspace_effects_committed": True,
            "workspace_effect_count": len(paths),
            "workspace_effect_paths": paths,
            "mutation_scope_count": len(self.scopes),
            "mutation_scope_digest": _scope_digest(self.scopes),
        }

    def discard(self) -> dict[str, object]:
        if not self._closed and not self._recovery_required:
            self._prepared_changes = None
            self._prepared_evidence = None
            # Overlayfs leaves its private work/work directory mode 000 after
            # unmount. Restore owner traversal before removing the Core-owned
            # overlay tree; never follow a command-created symlink here.
            try:
                os.chmod(
                    self.work / "work",
                    stat.S_IRWXU,
                    follow_symlinks=False,
                )
            except (NotImplementedError, OSError):
                pass
            shutil.rmtree(self.root, ignore_errors=True)
            self._closed = not self.root.exists()
        return {
            "workspace_effects_committed": False,
            "workspace_effect_count": 0,
            "workspace_effect_paths": (),
            "mutation_scope_count": len(self.scopes),
            "mutation_scope_digest": _scope_digest(self.scopes),
        }

    def _validated_changes(self) -> tuple[_ChangedFile, ...]:
        raw_diff = scan_hosted_effect_overlay_upper(self.upper)
        if len(raw_diff.files) > MAX_HOSTED_EFFECT_FILES:
            raise RuntimeToolError("workspace_effect_file_limit_exceeded")
        _validate_overlay_root_metadata(
            baseline=self.upper_baseline_metadata,
            observed=raw_diff.root_metadata,
            has_entries=bool(raw_diff.files or raw_diff.directories),
        )
        changed_paths = tuple(item.path for item in raw_diff.files)
        for directory in raw_diff.directories:
            path = directory.path
            if _scope_for_path(self.scopes, path) is None:
                raise RuntimeToolError("workspace_effect_outside_declared_scope")
            if not self.filesystem.path_is_directory(path):
                raise RuntimeToolError("workspace_effect_directory_unsupported")
            live_metadata = self.filesystem.path_metadata(path, directory=True)
            if not preserved_metadata_matches(
                directory.metadata,
                live_metadata,
            ) or directory.metadata.atime_ns != live_metadata.atime_ns:
                raise RuntimeToolError("workspace_effect_metadata_unsupported")
            if not any(
                changed_path.startswith(path + "/")
                for changed_path in changed_paths
            ):
                raise RuntimeToolError("workspace_effect_directory_unsupported")
            if directory.metadata.mtime_ns != directory.metadata.ctime_ns:
                raise RuntimeToolError("workspace_effect_metadata_unsupported")
        total_bytes = 0
        prepared: list[_ChangedFile] = []
        for effect_file in raw_diff.files:
            path = effect_file.path
            content_bytes = effect_file.content
            if effect_file.metadata.link_count != 1:
                raise RuntimeToolError("workspace_effect_hardlink_unsupported")
            scope = _scope_for_path(self.scopes, path)
            if scope is None:
                raise RuntimeToolError("workspace_effect_outside_declared_scope")
            if PurePosixPath(path).name == "AGENTS.md":
                raise RuntimeToolError("workspace_instruction_shell_mutation_denied")
            parent = PurePosixPath(path).parent.as_posix()
            if not self.filesystem.path_is_directory(parent):
                raise RuntimeToolError("workspace_effect_parent_not_directory")
            if len(content_bytes) > MAX_HOSTED_EFFECT_FILE_BYTES:
                raise RuntimeToolError("workspace_effect_file_too_large")
            total_bytes += len(content_bytes)
            if total_bytes > MAX_HOSTED_EFFECT_TOTAL_BYTES:
                raise RuntimeToolError("workspace_effect_total_too_large")
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RuntimeToolError("workspace_effect_not_utf8") from error
            guard = prepare_mutation_instruction_guard(
                self.filesystem,
                workspace_root=self.workspace_root,
                path=path,
                expected_digest=scope.instruction_scope_digest,
                target_is_directory=False,
            )
            baseline = self.baseline.get(path)
            if baseline is not None:
                live_metadata = self.filesystem.path_metadata(
                    path,
                    directory=False,
                )
                if not preserved_metadata_matches(
                    effect_file.metadata,
                    live_metadata,
                ):
                    raise RuntimeToolError("workspace_effect_metadata_unsupported")
                if live_metadata.link_count != 1:
                    raise RuntimeToolError("workspace_effect_hardlink_unsupported")
                observation, _classification = self.filesystem.observe_file(
                    path,
                    provenance="tool_result",
                )
                if (
                    observation.resource_identity != baseline.resource_identity
                    or observation.resource_revision != baseline.resource_revision
                ):
                    raise RuntimeToolError("filesystem_resource_changed")
                if _existing_content_matches(
                    self.filesystem,
                    path=path,
                    content=content_bytes,
                    baseline=baseline,
                ):
                    raise RuntimeToolError("workspace_effect_metadata_unsupported")
            else:
                parent_metadata = self.filesystem.path_metadata(
                    parent,
                    directory=True,
                )
                expected_uid = os.geteuid()
                expected_gid = (
                    parent_metadata.gid
                    if parent_metadata.mode & stat.S_ISGID
                    else os.getegid()
                )
                if (
                    effect_file.metadata.mode & 0o7111
                    or effect_file.metadata.xattrs
                    or effect_file.metadata.uid != expected_uid
                    or effect_file.metadata.gid != expected_gid
                ):
                    raise RuntimeToolError("workspace_effect_metadata_unsupported")
            prepared.append(
                _ChangedFile(
                    path=path,
                    content=content,
                    baseline=baseline,
                    guard=guard,
                    create_mode=effect_file.metadata.mode,
                    create_uid=effect_file.metadata.uid,
                    create_gid=effect_file.metadata.gid,
                    target_atime_ns=effect_file.metadata.atime_ns,
                    target_mtime_ns=effect_file.metadata.mtime_ns,
                )
            )
        return tuple(prepared)


def parse_hosted_workspace_mutation_scopes(
    value: object,
) -> tuple[HostedWorkspaceMutationScope, ...]:
    """Require an explicit, bounded set; an empty set means read-only workspace."""
    if not isinstance(value, list) or len(value) > 32:
        raise RuntimeToolError("tool_arguments_invalid")
    scopes: list[HostedWorkspaceMutationScope] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "instruction_scope_digest",
        }:
            raise RuntimeToolError("tool_arguments_invalid")
        path = _normalized_relative_path(item.get("path"), allow_root=True)
        digest = str(item.get("instruction_scope_digest") or "")
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
            or path in seen
        ):
            raise RuntimeToolError("tool_arguments_invalid")
        seen.add(path)
        scopes.append(HostedWorkspaceMutationScope(path, digest.lower()))
    return tuple(sorted(scopes, key=lambda item: (_path_depth(item.path), item.path)))


def _scope_for_path(
    scopes: tuple[HostedWorkspaceMutationScope, ...],
    path: str,
) -> HostedWorkspaceMutationScope | None:
    matches = [scope for scope in scopes if _path_within(path, scope.path)]
    return max(matches, key=lambda item: _path_depth(item.path), default=None)


def _path_within(path: str, scope: str) -> bool:
    return scope == "." or path == scope or path.startswith(scope + "/")


def _path_depth(path: str) -> int:
    return 0 if path == "." else len(PurePosixPath(path).parts)


def _normalized_relative_path(value: object, *, allow_root: bool) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise RuntimeToolError("tool_arguments_invalid")
    path = PurePosixPath(value)
    parts = tuple(part for part in path.parts if part != ".")
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", "..", ".git"} for part in parts)
        or (parts and parts[0] == "runtime")
        or (not parts and not allow_root)
    ):
        raise RuntimeToolError("tool_arguments_invalid")
    return "/".join(parts) or "."


def _scope_digest(scopes: tuple[HostedWorkspaceMutationScope, ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            [scope.__dict__ for scope in scopes],
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _validate_overlay_root_metadata(
    *,
    baseline: ConfinedPathMetadata,
    observed: ConfinedPathMetadata,
    has_entries: bool,
) -> None:
    if (
        not preserved_metadata_matches(baseline, observed)
        or observed.atime_ns != baseline.atime_ns
    ):
        raise RuntimeToolError("workspace_effect_metadata_unsupported")
    if not has_entries:
        if observed.mtime_ns != baseline.mtime_ns:
            raise RuntimeToolError("workspace_effect_metadata_unsupported")
        return
    if observed.mtime_ns not in {baseline.mtime_ns, observed.ctime_ns}:
        raise RuntimeToolError("workspace_effect_metadata_unsupported")


def _existing_content_matches(
    filesystem: ConfinedWorkspaceFilesystem,
    *,
    path: str,
    content: bytes,
    baseline: _BaselineFile,
) -> bool:
    observed = filesystem.read_file_bytes_for_validation(
        path,
        max_bytes=MAX_HOSTED_EFFECT_FILE_BYTES + 1,
        expected_resource_identity=baseline.resource_identity,
        expected_resource_revision=baseline.resource_revision,
    )
    return observed == content if observed is not None else False


__all__ = [
    "HostedWorkspaceEffectOverlay",
    "HostedWorkspaceMutationScope",
    "parse_hosted_workspace_mutation_scopes",
]
