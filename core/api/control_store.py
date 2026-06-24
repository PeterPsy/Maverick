"""Control-plane persistence adapter wiring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from core.apps.store import AppCollections
from core.identity.store import IdentityCollections
from core.providers.store import ProviderCollections
from core.secrets.bootstrap import resolve_bootstrap_secret
from core.secrets.store import SecretCollections
from core.shared.json_file_collection import JsonFileCollection
from core.shared.mongo_document_collection import MongoDocumentCollection
from core.workspaces.store import WorkspaceCollections


DEFAULT_MONGO_DATABASE = "maverick"
DEFAULT_JSON_CONTROL_STORE_ROOT = "data/control-plane/json"

MONGO_COLLECTION_UNIQUE_INDEXES: dict[str, tuple[tuple[str, ...], ...]] = {
    "workspaces": (("workspace_id",),),
    "workspace_memberships": (("membership_id",), ("user_id", "workspace_id")),
    "workspace_governance": (("workspace_id",),),
    "workspace_quotas": (("workspace_id",),),
    "active_workspace_selections": (("user_id",),),
    "identity_users": (("user_id",), ("username",)),
    "identity_credentials": (("user_id",),),
    "identity_auth_sessions": (("session_id",),),
    "app_sources": (("source_id",),),
    "workspace_local_app_projects": (("workspace_id", "app_id"),),
    "workspace_app_bindings": (("workspace_id", "app_id"),),
    "workspace_app_dependency_selections": (("workspace_id", "consumer_app_id", "alias"),),
    "provider_definitions": (("provider_id",),),
    "provider_credential_bindings": (("binding_id",),),
    "provider_selections": (("workspace_id",),),
    "provider_hosted_selections": (("workspace_id", "profile"),),
    "provider_speech_selections": (("workspace_id", "profile"),),
    "runtime_api_tokens": (("token_id",),),
    "secrets": (("secret_id",), ("alias",)),
    "secret_values": (("secret_id",),),
    "secret_bindings": (("binding_id",),),
    "secret_grants": (("grant_id",),),
}


@dataclass(frozen=True)
class ControlStoreSettings:
    """Configuration for installation-level control-plane persistence."""

    kind: str
    json_root: Path
    mongo_uri: str | None = None
    mongo_database: str = DEFAULT_MONGO_DATABASE
    mongo_username: str | None = None
    mongo_password_ref: str | None = None

    @classmethod
    def from_environment(
        cls,
        *,
        repository_root: Path,
        environment: Mapping[str, str] | None = None,
    ) -> "ControlStoreSettings":
        env = environment if environment is not None else os.environ
        mongo_uri = env.get("MAVERICK_MONGODB_URI", "").strip() or None
        json_root = Path(
            env.get("MAVERICK_JSON_CONTROL_STORE_ROOT", "").strip()
            or env.get("MAVERICK_LOCAL_STATE_ROOT", "").strip()
            or DEFAULT_JSON_CONTROL_STORE_ROOT
        )
        if not json_root.is_absolute():
            json_root = repository_root / json_root
        configured_kind = env.get("MAVERICK_CONTROL_STORE", "").strip().lower()
        kind = _resolve_control_store_kind(configured_kind=configured_kind, mongo_uri=mongo_uri, environment=env)
        mongo_database = env.get("MAVERICK_MONGODB_DATABASE", "").strip() or _database_from_mongo_uri(mongo_uri) or DEFAULT_MONGO_DATABASE
        mongo_username = env.get("MAVERICK_MONGODB_USERNAME", "").strip() or None
        mongo_password_ref = env.get("MAVERICK_MONGODB_PASSWORD_REF", "").strip() or None
        return cls(
            kind=kind,
            json_root=json_root,
            mongo_uri=mongo_uri,
            mongo_database=mongo_database,
            mongo_username=mongo_username,
            mongo_password_ref=mongo_password_ref,
        )


@dataclass(frozen=True)
class ControlPlaneCollections:
    """Collection bundles selected for platform-owned control-plane stores."""

    workspace: WorkspaceCollections
    identity: IdentityCollections
    apps: AppCollections
    provider: ProviderCollections
    runtime_api_tokens: Any | None
    secrets: SecretCollections


@dataclass(frozen=True)
class ControlPlaneCollectionSpec:
    """One authoritative control-plane collection to inventory or migrate."""

    name: str
    collection: Any


def build_control_plane_collections(settings: ControlStoreSettings) -> ControlPlaneCollections:
    """Build control-plane collections for the configured persistence adapter."""
    if settings.kind == "mongo":
        return _build_mongo_collections(settings)
    return _build_json_collections(settings.json_root)


def control_plane_collection_specs(collections: ControlPlaneCollections) -> list[ControlPlaneCollectionSpec]:
    """Return every persisted control-plane collection owned by the active adapter."""
    specs = [
        ControlPlaneCollectionSpec("workspaces", collections.workspace.workspaces),
        ControlPlaneCollectionSpec("workspace_memberships", collections.workspace.memberships),
        ControlPlaneCollectionSpec("workspace_governance", collections.workspace.governance),
        ControlPlaneCollectionSpec("workspace_quotas", collections.workspace.quotas),
        ControlPlaneCollectionSpec("active_workspace_selections", collections.workspace.active_workspace_selections),
        ControlPlaneCollectionSpec("identity_users", collections.identity.users),
        ControlPlaneCollectionSpec("identity_credentials", collections.identity.credentials),
        ControlPlaneCollectionSpec("identity_auth_sessions", collections.identity.auth_sessions),
        ControlPlaneCollectionSpec("app_sources", collections.apps.app_sources),
        ControlPlaneCollectionSpec("workspace_local_app_projects", collections.apps.workspace_local_app_projects),
        ControlPlaneCollectionSpec("workspace_app_bindings", collections.apps.workspace_app_bindings),
        ControlPlaneCollectionSpec(
            "workspace_app_dependency_selections",
            collections.apps.workspace_app_dependency_selections,
        ),
        ControlPlaneCollectionSpec("provider_definitions", collections.provider.definitions),
        ControlPlaneCollectionSpec("provider_credential_bindings", collections.provider.bindings),
        ControlPlaneCollectionSpec("provider_selections", collections.provider.selections),
        ControlPlaneCollectionSpec("provider_hosted_selections", collections.provider.hosted_selections),
        ControlPlaneCollectionSpec("runtime_api_tokens", collections.runtime_api_tokens),
        ControlPlaneCollectionSpec("secrets", collections.secrets.secrets),
        ControlPlaneCollectionSpec("secret_values", collections.secrets.values),
        ControlPlaneCollectionSpec("secret_bindings", collections.secrets.bindings),
        ControlPlaneCollectionSpec("secret_grants", collections.secrets.grants),
    ]
    return [spec for spec in specs if spec.collection is not None]


def _build_json_collections(json_root: Path) -> ControlPlaneCollections:
    app_state_root = json_root / "apps"
    workspace_state_root = json_root / "workspaces"
    identity_state_root = json_root / "identity"
    secret_state_root = json_root / "secrets"
    provider_state_root = json_root / "providers"
    return ControlPlaneCollections(
        workspace=WorkspaceCollections(
            workspaces=JsonFileCollection(workspace_state_root / "workspaces.json"),
            memberships=JsonFileCollection(workspace_state_root / "memberships.json"),
            governance=JsonFileCollection(workspace_state_root / "governance.json"),
            quotas=JsonFileCollection(workspace_state_root / "quotas.json"),
            active_workspace_selections=JsonFileCollection(
                workspace_state_root / "active_workspace_selections.json"
            ),
        ),
        identity=IdentityCollections(
            users=JsonFileCollection(identity_state_root / "users.json"),
            credentials=JsonFileCollection(identity_state_root / "credentials.json"),
            auth_sessions=JsonFileCollection(identity_state_root / "auth_sessions.json"),
        ),
        apps=AppCollections(
            app_sources=JsonFileCollection(app_state_root / "app_sources.json"),
            workspace_local_app_projects=JsonFileCollection(app_state_root / "workspace_local_app_projects.json"),
            workspace_app_bindings=JsonFileCollection(app_state_root / "workspace_app_bindings.json"),
            workspace_app_dependency_selections=JsonFileCollection(
                app_state_root / "workspace_app_dependency_selections.json"
            ),
        ),
        provider=ProviderCollections(
            definitions=JsonFileCollection(provider_state_root / "definitions.json"),
            bindings=JsonFileCollection(provider_state_root / "bindings.json"),
            selections=JsonFileCollection(provider_state_root / "selections.json"),
            hosted_selections=JsonFileCollection(provider_state_root / "hosted_selections.json"),
            speech_selections=JsonFileCollection(provider_state_root / "speech_selections.json"),
        ),
        runtime_api_tokens=JsonFileCollection(json_root / "runtime" / "api_tokens.json"),
        secrets=SecretCollections(
            secrets=JsonFileCollection(secret_state_root / "secrets.json"),
            values=JsonFileCollection(secret_state_root / "values.json"),
            bindings=JsonFileCollection(secret_state_root / "bindings.json"),
            grants=JsonFileCollection(secret_state_root / "grants.json"),
        ),
    )


def _build_mongo_collections(settings: ControlStoreSettings) -> ControlPlaneCollections:
    if not settings.mongo_uri:
        raise RuntimeError("MAVERICK_MONGODB_URI is required when MAVERICK_CONTROL_STORE=mongo.")
    database = _mongo_database(settings)
    collection = _MongoCollectionFactory(database)
    return ControlPlaneCollections(
        workspace=WorkspaceCollections(
            workspaces=collection("workspaces"),
            memberships=collection("workspace_memberships"),
            governance=collection("workspace_governance"),
            quotas=collection("workspace_quotas"),
            active_workspace_selections=collection("active_workspace_selections"),
        ),
        identity=IdentityCollections(
            users=collection("identity_users"),
            credentials=collection("identity_credentials"),
            auth_sessions=collection("identity_auth_sessions"),
        ),
        apps=AppCollections(
            app_sources=collection("app_sources"),
            workspace_local_app_projects=collection("workspace_local_app_projects"),
            workspace_app_bindings=collection("workspace_app_bindings"),
            workspace_app_dependency_selections=collection("workspace_app_dependency_selections"),
        ),
        provider=ProviderCollections(
            definitions=collection("provider_definitions"),
            bindings=collection("provider_credential_bindings"),
            selections=collection("provider_selections"),
            hosted_selections=collection("provider_hosted_selections"),
            speech_selections=collection("provider_speech_selections"),
        ),
        runtime_api_tokens=collection("runtime_api_tokens"),
        secrets=SecretCollections(
            secrets=collection("secrets"),
            values=collection("secret_values"),
            bindings=collection("secret_bindings"),
            grants=collection("secret_grants"),
        ),
    )


def _mongo_database(settings: ControlStoreSettings) -> Any:
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError("Install pymongo to use MAVERICK_CONTROL_STORE=mongo.") from exc
    kwargs: dict[str, Any] = {"tz_aware": True, "tzinfo": UTC}
    if settings.mongo_password_ref:
        if not settings.mongo_username:
            raise RuntimeError("MAVERICK_MONGODB_USERNAME is required when MAVERICK_MONGODB_PASSWORD_REF is set.")
        kwargs["username"] = settings.mongo_username
        kwargs["password"] = resolve_bootstrap_secret(settings.mongo_password_ref)
    elif settings.mongo_username:
        kwargs["username"] = settings.mongo_username
    client = MongoClient(settings.mongo_uri, **kwargs)
    return client[settings.mongo_database]


class _MongoCollectionFactory:
    def __init__(self, database: Any) -> None:
        self.database = database

    def __call__(
        self,
        name: str,
    ) -> MongoDocumentCollection:
        collection = self.database[name]
        ensure_mongo_collection_indexes(collection, name)
        return MongoDocumentCollection(collection)


def ensure_mongo_collection_indexes(collection: Any, name: str) -> None:
    for fields in MONGO_COLLECTION_UNIQUE_INDEXES.get(name, ()):
        index_spec = [(field, 1) for field in fields]
        index_name = "uniq_" + "_".join(fields)
        collection.create_index(index_spec, name=index_name, unique=True)


def _database_from_mongo_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    parsed = urlparse(uri)
    database = parsed.path.strip("/")
    if not database:
        return None
    return database.split("/", 1)[0]


def _resolve_control_store_kind(
    *,
    configured_kind: str,
    mongo_uri: str | None,
    environment: Mapping[str, str],
) -> str:
    if configured_kind == "mongodb":
        configured_kind = "mongo"
    if not configured_kind:
        if mongo_uri:
            return "mongo"
        return "json"
    if configured_kind not in {"json", "mongo"}:
        raise RuntimeError(f"Unsupported MAVERICK_CONTROL_STORE `{configured_kind}`.")
    return configured_kind
