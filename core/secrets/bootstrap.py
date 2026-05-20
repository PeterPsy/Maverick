"""Bootstrap-positioned core secret helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from core.secrets.key_material import load_secret_store_key
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.store import SecretCollections, SecretDocumentStore
from core.shared.json_file_collection import JsonFileCollection


DEFAULT_BOOTSTRAP_SECRET_STORE_ROOT = "data/bootstrap-secrets"


def bootstrap_secret_store_root(
    *,
    repository_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the local filesystem root for pre-adapter core secrets."""
    env = environment if environment is not None else os.environ
    configured = env.get("MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT", "").strip() or DEFAULT_BOOTSTRAP_SECRET_STORE_ROOT
    root = Path(configured)
    if root.is_absolute():
        return root
    return (repository_root or Path.cwd()) / root


def create_bootstrap_secret_store(
    *,
    root: Path | None = None,
    repository_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> SecretDocumentStore:
    """Build a document-backed store for secrets needed before the adapter is reachable."""
    secret_root = root or bootstrap_secret_store_root(repository_root=repository_root, environment=environment)
    return SecretDocumentStore(
        SecretCollections(
            secrets=JsonFileCollection(secret_root / "secrets.json"),
            values=JsonFileCollection(secret_root / "values.json"),
            bindings=JsonFileCollection(secret_root / "bindings.json"),
            grants=JsonFileCollection(secret_root / "grants.json"),
        ),
        key_loader=lambda: load_secret_store_key(environment),
    )


def resolve_bootstrap_secret(
    secret_ref: str,
    *,
    root: Path | None = None,
    repository_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Resolve one direct platform secret ref from the local bootstrap store."""
    store = create_bootstrap_secret_store(root=root, repository_root=repository_root, environment=environment)
    lease = resolve_secret_for_runtime(
        store,
        context=SecretResolutionContext(
            workspace_id=None,
            operator_request=True,
            allow_unbound_secret_refs=True,
            platform_delivery=True,
        ),
        secret_ref=secret_ref,
    )
    return lease.value
