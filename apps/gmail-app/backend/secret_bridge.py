"""Gmail App helpers for resolving app-scoped Maverick secrets from CLI/MCP entrypoints."""

from __future__ import annotations

from pathlib import Path
import sys


def resolve_local_app_secrets(*, workspace_id: str, app_id: str = "gmail-app") -> dict[str, str]:
    """Resolve app-scoped secrets when the app is invoked outside the hosted backend mount."""
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from core.secrets.service import resolve_app_secret
        from core.secrets.store import MongoSecretStore, SecretCollections
        from core.shared.json_file_collection import JsonFileCollection
    except Exception:
        return {}
    secret_state_root = repo_root / ".maverick" / "local-state" / "secrets"
    store = MongoSecretStore(
        SecretCollections(
            secrets=JsonFileCollection(secret_state_root / "secrets.json"),
            values=JsonFileCollection(secret_state_root / "values.json"),
            bindings=JsonFileCollection(secret_state_root / "bindings.json"),
        )
    )
    resolved: dict[str, str] = {}
    try:
        bindings = store.list_secret_bindings(workspace_id=workspace_id, app_id=app_id, scope="app")
    except Exception:
        return {}
    for binding in bindings:
        if binding.status != "active":
            continue
        try:
            resolved[binding.logical_name] = resolve_app_secret(
                store,
                workspace_id=workspace_id,
                app_id=app_id,
                logical_name=binding.logical_name,
            ).value
        except Exception:
            continue
    return resolved
