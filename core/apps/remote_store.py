"""Install app bundles from an authenticated platform app-store workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import Any
from urllib.parse import urljoin
from urllib.request import urlopen

from core.apps.contracts import parse_app_contract_file
from core.apps.errors import AppLifecycleError
from core.apps.paths import external_app_bundles_root
from core.apps.service import install_store_app, register_app_source_from_contract
from core.apps.store import AppStore
from core.observability.service import record_platform_audit, record_platform_event
from core.workspaces.service import ensure_workspace_layout
from core.workspaces.store import WorkspaceStore


DEFAULT_PUBLIC_CATALOG_URL = "https://maverick-app-store.versy.ai"


@dataclass(frozen=True)
class RemoteAppVersion:
    """Version metadata returned by a Maverick app catalog."""

    app_id: str
    version: str
    name: str
    artifact_url: str
    sha256: str


def _read_url_bytes(url: str, *, timeout_seconds: int = 30) -> bytes:
    with urlopen(url, timeout=timeout_seconds) as response:
        return response.read()


def _read_url_json(url: str, *, timeout_seconds: int = 30) -> dict[str, Any]:
    payload = json.loads(_read_url_bytes(url, timeout_seconds=timeout_seconds).decode("utf-8"))
    if not isinstance(payload, dict):
        raise AppLifecycleError(f"Remote app-store URL `{url}` did not return a JSON object.")
    return payload


def catalog_base_url(base_url: str | None = None) -> str:
    return (base_url or DEFAULT_PUBLIC_CATALOG_URL).strip().rstrip("/")


def fetch_remote_catalog(base_url: str | None = None) -> dict[str, Any]:
    """Fetch the public app catalog from a configured Maverick App Store."""
    resolved_base_url = catalog_base_url(base_url)
    return _read_url_json(urljoin(resolved_base_url.rstrip("/") + "/", "api/apps"))


def resolve_remote_app_version(base_url: str, *, app_id: str, version: str | None = None) -> RemoteAppVersion:
    """Return the requested app version from the remote catalog."""
    catalog = fetch_remote_catalog(base_url)
    for item in catalog.get("items", []):
        if not isinstance(item, dict) or item.get("app_id") != app_id:
            continue
        target_version = version or str(item.get("latest_version") or "")
        for candidate in item.get("versions", []):
            if not isinstance(candidate, dict) or candidate.get("version") != target_version:
                continue
            artifact_url = str(candidate.get("artifact_download_url") or candidate.get("artifact_url") or "")
            if not artifact_url:
                raise AppLifecycleError(f"Remote app `{app_id}` version `{target_version}` has no artifact URL.")
            if artifact_url.startswith("/"):
                artifact_url = urljoin(base_url.rstrip("/") + "/", artifact_url.lstrip("/"))
            sha256 = str(candidate.get("sha256") or "")
            if not sha256:
                raise AppLifecycleError(f"Remote app `{app_id}` version `{target_version}` has no SHA-256 checksum.")
            return RemoteAppVersion(
                app_id=app_id,
                version=target_version,
                name=str(candidate.get("name") or item.get("name") or app_id),
                artifact_url=artifact_url,
                sha256=sha256,
            )
    suffix = f" version `{version}`" if version else ""
    raise AppLifecycleError(f"Remote app `{app_id}`{suffix} was not found in the configured catalog.")


def _assert_safe_tar_member(destination: Path, member: tarfile.TarInfo) -> None:
    target = (destination / member.name).resolve()
    if destination.resolve() != target and destination.resolve() not in target.parents:
        raise AppLifecycleError(f"Unsafe archive member `{member.name}` escapes the bundle staging directory.")
    if member.issym() or member.islnk():
        raise AppLifecycleError(f"Archive member `{member.name}` is a link, which is not allowed in app bundles.")


def _extract_bundle(archive_path: Path, staging_root: Path) -> Path:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            _assert_safe_tar_member(staging_root, member)
        archive.extractall(staging_root, members=members, filter="data")
    contract_roots = sorted(path.parent for path in staging_root.rglob("app_contract.json"))
    if len(contract_roots) != 1:
        raise AppLifecycleError("A remote app bundle must contain exactly one app_contract.json file.")
    return contract_roots[0]


def stage_remote_app_bundle(
    *,
    base_url: str,
    app_id: str,
    version: str | None,
    start_path: Path,
) -> tuple[Path, RemoteAppVersion]:
    """Download, verify, and stage one remote app bundle under the trusted bundle root."""
    resolved = resolve_remote_app_version(base_url, app_id=app_id, version=version)
    bundle_root = external_app_bundles_root(start_path=start_path) / resolved.app_id / resolved.version
    bundle_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="maverick-app-store-") as temp:
        temp_root = Path(temp)
        archive_path = temp_root / "artifact.tar.gz"
        archive_bytes = _read_url_bytes(resolved.artifact_url, timeout_seconds=60)
        actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        if actual_sha256 != resolved.sha256:
            raise AppLifecycleError(
                f"Checksum mismatch for `{resolved.app_id}` `{resolved.version}`: expected {resolved.sha256}, got {actual_sha256}."
            )
        archive_path.write_bytes(archive_bytes)
        extracted_root = _extract_bundle(archive_path, temp_root / "extract")
        staged_root = temp_root / "staged"
        shutil.copytree(extracted_root, staged_root)
        if bundle_root.exists():
            shutil.rmtree(bundle_root)
        shutil.copytree(staged_root, bundle_root)
    return bundle_root, resolved


def install_remote_store_app(
    app_store: AppStore,
    workspace_store: WorkspaceStore,
    *,
    catalog_base_url: str,
    app_id: str,
    version: str | None,
    workspace_ids: list[str],
    start_path: Path,
    now: datetime | None = None,
    observability_store=None,
) -> dict[str, Any]:
    """Install one remote app-store artifact and enable it for selected workspaces."""
    source_root, resolved = stage_remote_app_bundle(
        base_url=catalog_base_url,
        app_id=app_id,
        version=version,
        start_path=start_path,
    )
    parsed = parse_app_contract_file(source_root)
    if parsed.app_id != resolved.app_id or parsed.version != resolved.version:
        raise AppLifecycleError(
            f"Remote catalog advertised `{resolved.app_id}` `{resolved.version}` but bundle declares `{parsed.app_id}` `{parsed.version}`."
        )
    source = register_app_source_from_contract(
        app_store,
        source_kind="external_bundle",
        source_path=str(source_root),
        source_id=f"app-store:{resolved.app_id}:{resolved.version}",
        now=now,
    )
    bindings = []
    for workspace_id in workspace_ids:
        workspace_store.get_workspace(workspace_id)
        ensure_workspace_layout(workspace_id, start_path=start_path)
        binding = install_store_app(
            app_store,
            source_id=source.source_id,
            workspace_id=workspace_id,
            enabled=True,
            now=now,
            start_path=start_path,
            observability_store=observability_store,
        )
        bindings.append(binding)
    if observability_store is not None:
        payload = {
            "app_id": resolved.app_id,
            "version": resolved.version,
            "source_id": source.source_id,
            "workspace_ids": workspace_ids,
        }
        record_platform_audit(
            observability_store,
            action="app_store.install_remote",
            status="succeeded",
            source_domain="apps",
            detail=f"Installed remote app `{resolved.app_id}` `{resolved.version}`.",
            app_id=resolved.app_id,
            payload=payload,
        )
        record_platform_event(
            observability_store,
            event_type="app_store.remote_app_installed",
            event_plane="platform",
            source_domain="apps",
            app_id=resolved.app_id,
            payload=payload,
        )
    return {
        "app": {"app_id": resolved.app_id, "name": resolved.name, "version": resolved.version},
        "source": {"source_id": source.source_id, "source_path": source.source_path},
        "bindings": [
            {
                "workspace_id": binding.workspace_id,
                "app_id": binding.app_id,
                "status": binding.status,
                "active_version": binding.active_version,
            }
            for binding in bindings
        ],
    }
