"""Workspace-domain services."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
import unicodedata

from core.execution_policy.service import resolve_workspace_execution_profile
from core.workspaces.errors import WorkspaceNotFoundError
from core.workspaces.models import (
    ActiveWorkspaceSelection,
    WorkspacePaths,
    WorkspaceGovernanceRecord,
    WorkspaceMembershipRecord,
    WorkspaceQuotaRecord,
    WorkspaceRecord,
)
from core.workspaces.paths import workspace_paths
from core.workspaces.store import WorkspaceStore


def ensure_workspace_layout(workspace_id: str, start_path: Path | None = None) -> WorkspacePaths:
    """Create the canonical directory layout for one workspace if it does not exist."""
    paths = workspace_paths(workspace_id=workspace_id, start_path=start_path)
    directories = (
        paths.root,
        paths.apps,
        paths.data,
        paths.logs,
        paths.runtime,
        paths.storage,
        paths.uploaded_storage,
        paths.generated_storage,
        paths.tests,
        paths.tmp,
    )
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def ensure_default_workspace(start_path: Path | None = None) -> WorkspacePaths:
    """Create the default workspace root using the canonical layout."""
    return ensure_workspace_layout(workspace_id="default", start_path=start_path)


def utcnow() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(tz=UTC)


def slugify_workspace_name(name: str) -> str:
    """Build a filesystem-safe slug from a workspace name."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.strip().lower()).strip("-")
    return slug or "workspace"


def build_workspace_record(
    *,
    workspace_id: str,
    name: str,
    slug: str,
    description: str | None = None,
    created_by_user_id: str | None = None,
    now: datetime | None = None,
) -> WorkspaceRecord:
    """Build a canonical workspace registry record."""
    timestamp = now or utcnow()
    return WorkspaceRecord(
        workspace_id=workspace_id,
        slug=slug,
        name=name,
        description=description,
        status="active",
        created_by_user_id=created_by_user_id,
        created_at=timestamp,
        updated_at=timestamp,
    )


def build_workspace_membership(
    *,
    membership_id: str,
    workspace_id: str,
    user_id: str,
    role: str = "member",
    now: datetime | None = None,
) -> WorkspaceMembershipRecord:
    """Build one workspace membership record."""
    timestamp = now or utcnow()
    normalized_role = "admin" if role == "admin" else "member"
    return WorkspaceMembershipRecord(
        membership_id=membership_id,
        workspace_id=workspace_id,
        user_id=user_id,
        role=normalized_role,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
    )


def default_workspace_governance(workspace_id: str, now: datetime | None = None) -> WorkspaceGovernanceRecord:
    """Build the default governance switches for one workspace."""
    timestamp = now or utcnow()
    return WorkspaceGovernanceRecord(
        workspace_id=workspace_id,
        allow_app_installation=True,
        allow_agent_creation=True,
        allow_agent_management=True,
        allow_custom_apps=True,
        allow_full_access_runtime=workspace_id == "default",
        created_at=timestamp,
        updated_at=timestamp,
    )


def default_workspace_quota(workspace_id: str, now: datetime | None = None) -> WorkspaceQuotaRecord:
    """Build the default quota envelope for one workspace."""
    timestamp = now or utcnow()
    return WorkspaceQuotaRecord(
        workspace_id=workspace_id,
        max_agent_instances=None if workspace_id == "default" else 3,
        max_installed_apps=None,
        max_storage_bytes=None,
        created_at=timestamp,
        updated_at=timestamp,
    )


def ensure_default_workspace_record(store: WorkspaceStore, now: datetime | None = None) -> WorkspaceRecord:
    """Ensure the default workspace registry record exists."""
    timestamp = now or utcnow()
    try:
        record = store.get_workspace("default")
    except WorkspaceNotFoundError:
        record = build_workspace_record(
            workspace_id="default",
            name="Default",
            slug="default",
            description="Default workspace for the current Maverick installation.",
            created_by_user_id=None,
            now=timestamp,
        )
        store.save_workspace(record)
    try:
        store.get_governance("default")
    except WorkspaceNotFoundError:
        store.save_governance(default_workspace_governance(workspace_id="default", now=timestamp))
    try:
        store.get_quota("default")
    except WorkspaceNotFoundError:
        store.save_quota(default_workspace_quota(workspace_id="default", now=timestamp))
    return record


def create_workspace(
    store: WorkspaceStore,
    *,
    name: str,
    description: str | None = None,
    created_by_user_id: str,
    creator_role: str = "admin",
    now: datetime | None = None,
) -> WorkspaceRecord:
    """Create a workspace record, governance record, quota record, and creator membership."""
    timestamp = now or utcnow()
    base_slug = slugify_workspace_name(name)
    workspace_id = base_slug
    suffix = 2
    existing_ids = {workspace.workspace_id for workspace in store.list_workspaces()}
    while workspace_id in existing_ids:
        workspace_id = f"{base_slug}-{suffix}"
        suffix += 1

    record = build_workspace_record(
        workspace_id=workspace_id,
        name=name,
        slug=workspace_id,
        description=description,
        created_by_user_id=created_by_user_id,
        now=timestamp,
    )
    store.save_workspace(record)
    store.save_governance(default_workspace_governance(workspace_id=workspace_id, now=timestamp))
    store.save_quota(default_workspace_quota(workspace_id=workspace_id, now=timestamp))
    ensure_workspace_membership(
        store,
        membership_id=f"{workspace_id}:{created_by_user_id}",
        workspace_id=workspace_id,
        user_id=created_by_user_id,
        role=creator_role,
        now=timestamp,
    )
    set_active_workspace_for_user(
        store,
        user_id=created_by_user_id,
        workspace_id=workspace_id,
        now=timestamp,
    )
    return record


def ensure_workspace_membership(
    store: WorkspaceStore,
    *,
    membership_id: str,
    workspace_id: str,
    user_id: str,
    role: str = "member",
    now: datetime | None = None,
) -> WorkspaceMembershipRecord:
    """Ensure one user has an active membership in one workspace."""
    record = build_workspace_membership(
        membership_id=membership_id,
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        now=now,
    )
    return store.save_membership(record)


def set_active_workspace_for_user(
    store: WorkspaceStore,
    *,
    user_id: str,
    workspace_id: str,
    now: datetime | None = None,
) -> ActiveWorkspaceSelection:
    """Persist the active workspace selection for one user."""
    selection = ActiveWorkspaceSelection(
        user_id=user_id,
        workspace_id=workspace_id,
        updated_at=now or utcnow(),
    )
    return store.set_active_workspace(selection)


def get_active_workspace_for_user(store: WorkspaceStore, *, user_id: str) -> ActiveWorkspaceSelection | None:
    """Return the active workspace selection for one user, if it exists."""
    return store.get_active_workspace(user_id)


def resolve_active_workspace_for_user(
    store: WorkspaceStore,
    *,
    user_id: str,
    now: datetime | None = None,
) -> ActiveWorkspaceSelection | None:
    """Resolve an active workspace the user is allowed to enter.

    A missing or stale selection must never fall back to a workspace where the
    user has no active membership. This is security-sensitive because the
    default workspace may allow full-access runtime execution.
    """
    selected = store.get_active_workspace(user_id)
    active_memberships = [
        membership
        for membership in store.list_memberships_for_user(user_id)
        if membership.status == "active"
    ]
    active_workspace_ids = {membership.workspace_id for membership in active_memberships}
    if selected is not None and selected.workspace_id in active_workspace_ids:
        try:
            store.get_workspace(selected.workspace_id)
        except WorkspaceNotFoundError:
            pass
        else:
            return selected

    fallback_workspace_id = _fallback_workspace_id(active_workspace_ids)
    if fallback_workspace_id is None:
        return None
    try:
        store.get_workspace(fallback_workspace_id)
    except WorkspaceNotFoundError:
        return None
    return set_active_workspace_for_user(
        store,
        user_id=user_id,
        workspace_id=fallback_workspace_id,
        now=now,
    )


def _fallback_workspace_id(active_workspace_ids: set[str]) -> str | None:
    if not active_workspace_ids:
        return None
    if "default" in active_workspace_ids:
        return "default"
    return sorted(active_workspace_ids)[0]


def workspace_execution_profile(workspace_id: str, requested_mode: str | None = None):
    """Resolve the effective execution profile for one workspace."""
    return resolve_workspace_execution_profile(workspace_id=workspace_id, requested_mode=requested_mode)
