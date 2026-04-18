"""Workspace export discovery and coordination helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.apps.contracts import CURRENT_APP_CONTRACT_VERSION
from core.apps.lifecycle import (
    load_contract_from_source_record,
    load_contract_from_workspace_project,
    run_lifecycle_hook,
)
from core.apps.models import AppContractDescriptor, WorkspaceAppBindingRecord
from core.apps.store import AppStore
from core.apps.errors import AppLifecycleError
from core.workspaces.errors import WorkspaceExportError
from core.workspaces.inventory import FILE_INVENTORY_SCHEMA_VERSION, build_file_identity
from core.workspaces.models import (
    ExportManifest,
    ExportedAppReference,
    WorkspaceExportBundle,
    WorkspaceExportParticipant,
)


WORKSPACE_EXPORT_SCHEMA_VERSION = "2"
DEFAULT_EXPORT_EXCLUDED_PREFIXES = ("logs/", "runtime/", "tmp/", ".maverick/")


def _timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def include_in_workspace_export(*, file_path: Path, workspace_root: Path) -> bool:
    """Return whether one file should be included in a workspace export snapshot."""
    relative_path = file_path.resolve().relative_to(workspace_root.resolve()).as_posix()
    return not relative_path.startswith(DEFAULT_EXPORT_EXCLUDED_PREFIXES)


def discover_workspace_export_files(workspace_root: Path) -> list[Path]:
    """Discover exportable files from one workspace root."""
    discovered = [
        path.resolve()
        for path in workspace_root.rglob("*")
        if path.is_file() and include_in_workspace_export(file_path=path, workspace_root=workspace_root)
    ]
    return sorted(discovered)


def build_export_manifest(
    workspace_id: str,
    workspace_root: Path,
    files: list[Path],
    *,
    app_bindings: list[WorkspaceAppBindingRecord] | None = None,
    schema_versions: dict[str, str] | None = None,
) -> ExportManifest:
    """Build a canonical workspace export manifest."""
    identities = [
        build_file_identity(file_path=file_path, workspace_root=workspace_root)
        for file_path in sorted(files)
        if include_in_workspace_export(file_path=file_path, workspace_root=workspace_root)
    ]
    known_apps = [
        ExportedAppReference(
            app_id=binding.app_id,
            version=binding.active_version,
            status=binding.status,
            source_kind=binding.source_kind,
            source_record_id=binding.source_record_id,
        )
        for binding in sorted(app_bindings or [], key=lambda item: item.app_id)
    ]
    return ExportManifest(
        manifest_version=WORKSPACE_EXPORT_SCHEMA_VERSION,
        workspace_id=workspace_id,
        exported_at=_timestamp(),
        schema_versions=schema_versions
        or {
            "workspace_export": WORKSPACE_EXPORT_SCHEMA_VERSION,
            "file_inventory": FILE_INVENTORY_SCHEMA_VERSION,
            "app_contract": CURRENT_APP_CONTRACT_VERSION,
        },
        known_apps=known_apps,
        files=identities,
    )


def _participant_for_binding(
    store: AppStore,
    *,
    binding: WorkspaceAppBindingRecord,
    start_path: Path | None = None,
) -> tuple[WorkspaceExportParticipant, Path, AppContractDescriptor]:
    if binding.source_kind == "workspace_local_project":
        project = store.get_workspace_local_app_project(workspace_id=binding.workspace_id, app_id=binding.app_id)
        source_root, parsed = load_contract_from_workspace_project(project, start_path=start_path)
    else:
        source = store.get_app_source(binding.source_record_id)
        source_root, parsed = load_contract_from_source_record(source, start_path=start_path)

    export_hook_path = parsed.contract.entrypoints.hooks.get("export")
    use_export_hook = parsed.contract.lifecycle.export and export_hook_path is not None
    participant = WorkspaceExportParticipant(
        app_id=binding.app_id,
        status=binding.status,
        version=binding.active_version,
        strategy="export_hook" if use_export_hook else "filesystem_snapshot",
        source_kind=binding.source_kind,
        source_record_id=binding.source_record_id,
        export_hook_path=export_hook_path,
    )
    return participant, source_root, parsed.contract


def plan_workspace_export(
    workspace_id: str,
    *,
    app_store: AppStore | None = None,
    start_path: Path | None = None,
) -> list[WorkspaceExportParticipant]:
    """Plan how installed workspace apps participate in one workspace export."""
    if app_store is None:
        return []
    bindings = app_store.list_workspace_app_bindings(workspace_id)
    return [
        _participant_for_binding(app_store, binding=binding, start_path=start_path)[0]
        for binding in sorted(bindings, key=lambda item: item.app_id)
    ]


def export_workspace_bundle(
    workspace_id: str,
    workspace_root: Path,
    *,
    app_store: AppStore | None = None,
    start_path: Path | None = None,
) -> WorkspaceExportBundle:
    """Coordinate a minimal workspace export snapshot for Phase 13 unblocker work."""
    bindings = app_store.list_workspace_app_bindings(workspace_id) if app_store is not None else []
    participants: list[WorkspaceExportParticipant] = []
    if app_store is not None:
        for binding in sorted(bindings, key=lambda item: item.app_id):
            participant, source_root, contract = _participant_for_binding(app_store, binding=binding, start_path=start_path)
            participants.append(participant)
            if participant.strategy == "export_hook":
                try:
                    run_lifecycle_hook(source_root, contract, hook_name="export")
                except AppLifecycleError as error:
                    raise WorkspaceExportError(
                        f"Workspace export failed while running export hook for app `{binding.app_id}`."
                    ) from error
    files = discover_workspace_export_files(workspace_root)
    manifest = build_export_manifest(
        workspace_id,
        workspace_root,
        files,
        app_bindings=bindings,
    )
    return WorkspaceExportBundle(manifest=manifest, participants=participants)
