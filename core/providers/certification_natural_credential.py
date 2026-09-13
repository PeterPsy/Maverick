"""Resolve the production OpenRouter credential without exporting it."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess

from core.api.control_store import (
    ControlStoreSettings,
    build_control_plane_collections,
)
from core.providers.store import ProviderDocumentStore
from core.secrets.models import SecretResolutionContext
from core.secrets.secret_resolution import resolve_secret_for_runtime
from core.secrets.store import SecretDocumentStore


def service_environment(control_root: Path) -> dict[str, str]:
    """Read only the service variables needed to open the control plane."""
    pid = int(
        subprocess.check_output(
            (
                "systemctl",
                "show",
                "-p",
                "MainPID",
                "--value",
                "maverick-core.service",
            ),
            text=True,
        ).strip()
    )
    allowed = {
        "MAVERICK_CONTROL_STORE",
        "MAVERICK_JSON_CONTROL_STORE_ROOT",
        "MAVERICK_LOCAL_STATE_ROOT",
        "MAVERICK_SECRET_KEY_FILE",
        "MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT",
        "MAVERICK_FEATURE_AGENTIC_PROFILES",
        "MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT",
        "MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME",
        "MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION",
        "MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE",
        "MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT",
        "MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW",
        "MAVERICK_FEATURE_PARALLEL_TOOL_CALLS",
    }
    result = {}
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" not in item:
            continue
        key_raw, value_raw = item.split(b"=", 1)
        key = key_raw.decode("ascii")
        if key not in allowed:
            continue
        value = value_raw.decode()
        if (
            key != "MAVERICK_CONTROL_STORE"
            and value
            and not Path(value).is_absolute()
        ):
            value = str((control_root / value).resolve())
        result[key] = value
    return result


def production_openrouter_credential(control_root: Path) -> str:
    """Lease the one active production credential into the current process."""
    with production_control_environment(control_root):
        collections = build_control_plane_collections(
            ControlStoreSettings.from_environment(repository_root=control_root)
        )
        provider_store = ProviderDocumentStore(collections.provider)
        secret_store = SecretDocumentStore(collections.secrets)
        bindings = [
            item
            for item in provider_store.list_provider_bindings(
                provider_id="openrouter",
                workspace_id="default",
            )
            if item.status == "active"
        ]
        if len(bindings) != 1:
            raise RuntimeError("production_provider_credential_binding_unavailable")
        return resolve_secret_for_runtime(
            secret_store,
            context=SecretResolutionContext(
                workspace_id="default",
                provider_id="openrouter",
                operator_request=True,
                allow_unbound_secret_refs=True,
                action="agentic_certification",
            ),
            secret_ref=bindings[0].secret_ref,
        ).value


@contextmanager
def production_control_environment(control_root: Path):
    """Temporarily expose the service's bounded control-plane environment."""
    environment = service_environment(control_root)
    saved = {key: os.environ.get(key) for key in environment}
    os.environ.update({key: value for key, value in environment.items() if value})
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


__all__ = [
    "production_control_environment",
    "production_openrouter_credential",
    "service_environment",
]
