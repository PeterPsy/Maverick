"""Install the selected unchanged official OpenDesign release."""

from __future__ import annotations

from pathlib import Path
import stat
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from core.apps.artifact_mounts import create_artifact_namespace
from core.shared.repository import discover_repository_root


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from official_opendesign_release import install_official_release, load_official_release  # noqa: E402


def main() -> None:
    payload = read_entrypoint_payload()
    if payload.app_id not in {"", "design-studio"}:
        raise SystemExit("Design Studio install payload has the wrong app identity.")
    data_dir = _ensure_real_directory(Path(payload.data_root) / "opendesign-native")
    _ensure_real_directory(Path(payload.data_root) / "delegations")
    release = load_official_release()
    namespace = create_artifact_namespace(
        repository_root=discover_repository_root(start_path=APP_ROOT),
        app_id="design-studio",
        artifact_id="opendesign",
    )
    installation = install_official_release(namespace / "official" / release.digest_key, release=release)
    emit_json(
        {
            "ok": True,
            "mode": "official-native",
            "data_directory": data_dir.name,
            "official_release": {
                "image": release.image,
                "version": release.version,
                "manifest_digest": release.manifest_digest,
                "source_commit": release.source_commit,
                "rootfs_snapshot_sha256": installation.rootfs_snapshot_sha256,
                "customizations": [],
            },
        }
    )


def _ensure_real_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SystemExit(f"Design Studio data path must be a real directory: {path.name}")
    path.chmod(0o700)
    return path.resolve(strict=True)


if __name__ == "__main__":
    main()
