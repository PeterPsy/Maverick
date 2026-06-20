"""Workspace-scoped registry and selection service for cross-app interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from core.apps.contract_common import _normalize_slug, _timestamp
from core.apps.errors import AppHostingError, WorkspaceAppBindingNotFoundError
from core.apps.models import (
    AppProvidedInterfaceDeclaration,
    AppRequiredInterfaceDeclaration,
    ParsedAppContract,
    WorkspaceAppDependencySelectionRecord,
)
from core.apps.store import AppStore
from core.apps.surfaces import enabled_workspace_app_bindings, resolve_workspace_app_surface
from core.authorization.service import can_mount_app_visibility
from core.identity.models import UserRecord

if TYPE_CHECKING:
    from core.workspaces.store import WorkspaceStore


def _version_major(version: str) -> str:
    return version.removeprefix("^").split(".", 1)[0]


def interface_version_matches(required_version: str, provided_version: str) -> bool:
    """Return whether a provider interface version satisfies one requirement."""
    if required_version.startswith("^"):
        return _version_major(required_version) == _version_major(provided_version)
    return required_version == provided_version


@dataclass(frozen=True)
class DependencyProviderCandidate:
    """Public metadata for one enabled provider app candidate."""

    app_id: str
    name: str
    version: str
    interface: str
    interface_version: str
    description: str
    surfaces: list[str]


@dataclass(frozen=True)
class DependencyResolution:
    """Resolved state for one required app interface alias."""

    alias: str
    interface: str
    version: str
    required: bool
    cardinality: str
    description: str
    status: str
    candidates: list[DependencyProviderCandidate]
    selected_provider_app_ids: list[str]
    stale_provider_app_ids: list[str]
    blocked_reason: str | None


def _candidate_payload(
    *,
    parsed: ParsedAppContract,
    provided: AppProvidedInterfaceDeclaration,
) -> DependencyProviderCandidate:
    return DependencyProviderCandidate(
        app_id=parsed.app_id,
        name=parsed.name,
        version=parsed.version,
        interface=provided.interface,
        interface_version=provided.version,
        description=provided.description,
        surfaces=list(provided.surfaces),
    )


def list_dependency_provider_candidates(
    store: AppStore,
    *,
    workspace_id: str,
    interface: str,
    version: str,
    consumer_app_id: str | None = None,
    user: UserRecord | None = None,
    workspace_store: "WorkspaceStore | None" = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
    start_path: Path | None = None,
) -> list[DependencyProviderCandidate]:
    """List enabled apps that provide one compatible generic app interface."""
    candidates: list[DependencyProviderCandidate] = []
    for binding in enabled_workspace_app_bindings(store, workspace_id=workspace_id):
        if consumer_app_id is not None and binding.app_id == consumer_app_id:
            continue
        try:
            _source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
        except AppHostingError:
            continue
        if workspace_store is not None:
            if not can_mount_app_visibility(
                workspace_store,
                user=user,
                workspace_id=workspace_id,
                platform_roles=parsed.contract.visibility.platform_roles,
                workspace_roles=parsed.contract.visibility.workspace_roles,
                capabilities=parsed.contract.visibility.capabilities,
                platform_role=platform_role,
                workspace_role=workspace_role,
            ):
                continue
        else:
            effective_platform_role = platform_role or (user.platform_role if user is not None else None)
            platform_roles = set(parsed.contract.visibility.platform_roles or [])
            workspace_roles = set(parsed.contract.visibility.workspace_roles or [])
            if platform_roles and effective_platform_role not in platform_roles:
                continue
            if workspace_roles and workspace_role not in workspace_roles:
                continue
        for provided in parsed.contract.provides:
            if provided.interface != interface:
                continue
            if not interface_version_matches(version, provided.version):
                continue
            candidates.append(_candidate_payload(parsed=parsed, provided=provided))
    return sorted(candidates, key=lambda item: (item.app_id, item.interface_version))


def _status_for_requirement(
    *,
    requirement: AppRequiredInterfaceDeclaration,
    candidates: list[DependencyProviderCandidate],
    selected_provider_app_ids: list[str],
    stale_provider_app_ids: list[str],
) -> tuple[str, str | None]:
    if stale_provider_app_ids:
        return "stale", "One or more selected provider apps are unavailable or no longer provide the required interface."
    if not candidates and requirement.required:
        return "missing_provider", "No enabled app provides the required interface."
    if not selected_provider_app_ids:
        if requirement.required:
            return "unresolved", "A provider app must be selected for this required interface."
        return "optional_unset", None
    if requirement.cardinality == "one" and len(selected_provider_app_ids) != 1:
        return "invalid_selection", "This interface requires exactly one selected provider app."
    return "resolved", None


def resolve_app_dependencies(
    store: AppStore,
    *,
    workspace_id: str,
    consumer_app_id: str,
    user: UserRecord | None = None,
    workspace_store: "WorkspaceStore | None" = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
    start_path: Path | None = None,
) -> dict[str, object]:
    """Resolve one consumer app's declared interface requirements in a workspace."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=consumer_app_id)
    if binding.status != "enabled":
        raise WorkspaceAppBindingNotFoundError(
            f"Workspace app `{consumer_app_id}` is not enabled in workspace `{workspace_id}`."
        )
    _source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
    selections = {
        selection.alias: selection
        for selection in store.list_workspace_app_dependency_selections(
            workspace_id=workspace_id,
            consumer_app_id=consumer_app_id,
        )
    }
    resolutions: list[DependencyResolution] = []
    for requirement in parsed.contract.requires:
        candidates = list_dependency_provider_candidates(
            store,
            workspace_id=workspace_id,
            interface=requirement.interface,
            version=requirement.version,
            consumer_app_id=consumer_app_id,
            user=user,
            workspace_store=workspace_store,
            platform_role=platform_role,
            workspace_role=workspace_role,
            start_path=start_path,
        )
        candidate_ids = {candidate.app_id for candidate in candidates}
        selection = selections.get(requirement.alias)
        configured_ids = list(selection.provider_app_ids) if selection else []
        selected_ids = [app_id for app_id in configured_ids if app_id in candidate_ids]
        stale_ids = [app_id for app_id in configured_ids if app_id not in candidate_ids]
        status, blocked_reason = _status_for_requirement(
            requirement=requirement,
            candidates=candidates,
            selected_provider_app_ids=selected_ids,
            stale_provider_app_ids=stale_ids,
        )
        resolutions.append(
            DependencyResolution(
                alias=requirement.alias,
                interface=requirement.interface,
                version=requirement.version,
                required=requirement.required,
                cardinality=requirement.cardinality,
                description=requirement.description,
                status=status,
                candidates=candidates,
                selected_provider_app_ids=selected_ids,
                stale_provider_app_ids=stale_ids,
                blocked_reason=blocked_reason,
            )
        )
    overall_status = "resolved"
    if any(item.status in {"missing_provider", "unresolved", "stale", "invalid_selection"} for item in resolutions):
        overall_status = "blocked"
    return {
        "workspace_id": workspace_id,
        "consumer_app_id": consumer_app_id,
        "status": overall_status,
        "dependencies": [
            {
                "alias": item.alias,
                "interface": item.interface,
                "version": item.version,
                "required": item.required,
                "cardinality": item.cardinality,
                "description": item.description,
                "status": item.status,
                "candidates": [candidate.__dict__ for candidate in item.candidates],
                "selected_provider_app_ids": item.selected_provider_app_ids,
                "stale_provider_app_ids": item.stale_provider_app_ids,
                "blocked_reason": item.blocked_reason,
            }
            for item in resolutions
        ],
    }


def save_app_dependency_selection(
    store: AppStore,
    *,
    workspace_id: str,
    consumer_app_id: str,
    alias: str,
    provider_app_ids: list[str],
    user: UserRecord | None = None,
    workspace_store: "WorkspaceStore | None" = None,
    platform_role: str | None = None,
    workspace_role: str | None = None,
    start_path: Path | None = None,
) -> dict[str, object]:
    """Validate and persist a provider selection for one consumer requirement alias."""
    binding = store.get_workspace_app_binding(workspace_id=workspace_id, app_id=consumer_app_id)
    if binding.status != "enabled":
        raise WorkspaceAppBindingNotFoundError(
            f"Workspace app `{consumer_app_id}` is not enabled in workspace `{workspace_id}`."
        )
    _source_root, parsed = resolve_workspace_app_surface(store, binding=binding, start_path=start_path)
    requirements = {requirement.alias: requirement for requirement in parsed.contract.requires}
    requirement = requirements.get(alias)
    if requirement is None:
        raise AppHostingError(f"App `{consumer_app_id}` does not declare required interface alias `{alias}`.")
    normalized_provider_ids = [str(app_id).strip() for app_id in provider_app_ids if str(app_id).strip()]
    if requirement.cardinality == "one" and len(normalized_provider_ids) > 1:
        raise AppHostingError(f"Required interface alias `{alias}` accepts only one provider app.")
    candidates = list_dependency_provider_candidates(
        store,
        workspace_id=workspace_id,
        interface=requirement.interface,
        version=requirement.version,
        consumer_app_id=consumer_app_id,
        user=user,
        workspace_store=workspace_store,
        platform_role=platform_role,
        workspace_role=workspace_role,
        start_path=start_path,
    )
    candidate_ids = {candidate.app_id for candidate in candidates}
    invalid_ids = [app_id for app_id in normalized_provider_ids if app_id not in candidate_ids]
    if invalid_ids:
        raise AppHostingError(f"Provider app(s) do not satisfy `{alias}`: {', '.join(invalid_ids)}.")
    if not normalized_provider_ids:
        store.delete_workspace_app_dependency_selection(
            workspace_id=workspace_id,
            consumer_app_id=consumer_app_id,
            alias=alias,
        )
        return resolve_app_dependencies(
            store,
            workspace_id=workspace_id,
            consumer_app_id=consumer_app_id,
            user=user,
            workspace_store=workspace_store,
            platform_role=platform_role,
            workspace_role=workspace_role,
            start_path=start_path,
        )
    now = _timestamp()
    existing = store.get_workspace_app_dependency_selection(
        workspace_id=workspace_id,
        consumer_app_id=consumer_app_id,
        alias=alias,
    )
    record = WorkspaceAppDependencySelectionRecord(
        selection_id=(existing.selection_id if existing else _normalize_slug(f"{workspace_id}-{consumer_app_id}-{alias}", fallback="dependency-selection")),
        workspace_id=workspace_id,
        consumer_app_id=consumer_app_id,
        alias=alias,
        provider_app_ids=normalized_provider_ids,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    store.save_workspace_app_dependency_selection(record)
    return resolve_app_dependencies(
        store,
        workspace_id=workspace_id,
        consumer_app_id=consumer_app_id,
        user=user,
        workspace_store=workspace_store,
        platform_role=platform_role,
        workspace_role=workspace_role,
        start_path=start_path,
    )
