"""Runtime skill catalog provider resolution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.apps.dependencies import list_dependency_provider_candidates, resolve_app_dependencies
from core.apps.errors import AppHostingError
from core.apps.store import AppStore
from core.identity.models import UserRecord

if TYPE_CHECKING:
    from core.workspaces.store import WorkspaceStore


RUNTIME_SKILLS_DEPENDENCY_ALIAS = "runtime-skills"
SKILL_CATALOG_INTERFACE = "skill.catalog"
SKILL_CATALOG_VERSION = "^1"


def runtime_skill_catalog_app_id_for_request(
    store: AppStore,
    *,
    workspace_id: str,
    source_app_id: str | None = None,
    explicit_app_id: str | None = None,
    user: UserRecord | None = None,
    workspace_store: "WorkspaceStore | None" = None,
    start_path: Path | None = None,
    allow_missing_source_app: bool = False,
) -> str | None:
    """Return the skill catalog provider app id for one runtime session request."""
    explicit = str(explicit_app_id or "").strip()
    if explicit:
        return validate_runtime_skill_catalog_provider_app_id(
            store,
            workspace_id=workspace_id,
            provider_app_id=explicit,
            user=user,
            workspace_store=workspace_store,
            start_path=start_path,
        )
    return selected_runtime_skill_catalog_app_id_for_source_app(
        store,
        workspace_id=workspace_id,
        source_app_id=source_app_id,
        user=user,
        workspace_store=workspace_store,
        start_path=start_path,
        allow_missing_source_app=allow_missing_source_app,
    )


def selected_runtime_skill_catalog_app_id_for_source_app(
    store: AppStore,
    *,
    workspace_id: str,
    source_app_id: str | None,
    user: UserRecord | None = None,
    workspace_store: "WorkspaceStore | None" = None,
    start_path: Path | None = None,
    allow_missing_source_app: bool = False,
) -> str | None:
    """Resolve a source app's selected runtime skill catalog dependency."""
    consumer_app_id = str(source_app_id or "").strip()
    if not consumer_app_id:
        return None
    try:
        dependencies = resolve_app_dependencies(
            store,
            workspace_id=workspace_id,
            consumer_app_id=consumer_app_id,
            user=user,
            workspace_store=workspace_store,
            start_path=start_path,
        )
    except AppHostingError:
        if allow_missing_source_app:
            return None
        raise
    dependency = next(
        (
            item
            for item in dependencies.get("dependencies", [])
            if isinstance(item, dict) and item.get("alias") == RUNTIME_SKILLS_DEPENDENCY_ALIAS
        ),
        None,
    )
    if dependency is None:
        return None
    provider_ids = dependency.get("selected_provider_app_ids")
    provider_id = str(provider_ids[0]).strip() if isinstance(provider_ids, list) and provider_ids else ""
    if provider_id:
        return provider_id
    raise AppHostingError(f"Dependency alias `{RUNTIME_SKILLS_DEPENDENCY_ALIAS}` has no selected provider app.")


def validate_runtime_skill_catalog_provider_app_id(
    store: AppStore,
    *,
    workspace_id: str,
    provider_app_id: str,
    user: UserRecord | None = None,
    workspace_store: "WorkspaceStore | None" = None,
    start_path: Path | None = None,
) -> str:
    """Validate that one enabled app provides the runtime skill catalog interface."""
    normalized = str(provider_app_id or "").strip()
    if not normalized:
        raise AppHostingError("Runtime skill catalog provider app id is required.")
    candidates = list_dependency_provider_candidates(
        store,
        workspace_id=workspace_id,
        interface=SKILL_CATALOG_INTERFACE,
        version=SKILL_CATALOG_VERSION,
        user=user,
        workspace_store=workspace_store,
        start_path=start_path,
    )
    if normalized not in {candidate.app_id for candidate in candidates}:
        raise AppHostingError(f"App `{normalized}` is not an enabled `{SKILL_CATALOG_INTERFACE}` provider.")
    return normalized
