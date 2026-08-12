"""Explicitly create the first empty OpenDesign bundle/data generation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import stat
from typing import Callable, Mapping

from opendesign_generation_control import load_generation_control, write_generation_control
from opendesign_generation_model import GenerationControl, GenerationControlError, LaunchSelection
from opendesign_migration_files import fsync_directory, remove_owned_directory


class BootstrapError(RuntimeError):
    """Raised when an empty generation cannot be bootstrapped safely."""


def bootstrap_empty_generation(
    root: Path,
    *,
    artifact_sha256: str,
    web_overlay_sha256: str,
    opendesign_version: str,
    verified_artifacts: Mapping[str, str],
    verified_overlays: Mapping[str, object],
    now: Callable[[], str] | None = None,
) -> tuple[GenerationControl, Path]:
    """Create one first generation only when no legacy or unknown data exists."""
    root = _validated_root(root)
    generation_id = f"gen_{artifact_sha256[:16]}"
    selection = LaunchSelection(
        artifact_sha256,
        web_overlay_sha256,
        opendesign_version,
        generation_id,
    )
    control_path = root / "control.json"
    if control_path.exists() or control_path.is_symlink():
        try:
            control = load_generation_control(
                root,
                verified_artifacts=verified_artifacts,
                verified_overlays=verified_overlays,
            )
        except GenerationControlError as exc:
            raise BootstrapError(f"existing OpenDesign generation control is invalid: {exc}") from exc
        if control.active != selection:
            raise BootstrapError("existing OpenDesign control selects a different generation")
        return control, root / "instances" / generation_id / "data"

    allowed = {"instances", "backups", "migrations", "web-activations"}
    existing = {child.name for child in root.iterdir()}
    if not existing.issubset(allowed):
        raise BootstrapError("OpenDesign root contains legacy or unknown data; controlled migration is required")
    for name in allowed:
        directory = root / name
        _require_empty_real_directory(directory, label=name)

    generation = root / "instances" / generation_id
    data_dir = generation / "data"
    generation.mkdir(mode=0o700)
    data_dir.mkdir(mode=0o700)
    fsync_directory(data_dir)
    fsync_directory(generation)
    fsync_directory(generation.parent)
    control = GenerationControl(
        active=selection,
        previous_release=None,
        previous_web=None,
        migration_id=None,
        web_activation_id=None,
        updated_at=(now or _utc_now)(),
    )
    try:
        write_generation_control(
            root,
            control,
            verified_artifacts=verified_artifacts,
            verified_overlays=verified_overlays,
        )
    except Exception:
        remove_owned_directory(generation, parent=root / "instances", label="incomplete bootstrap generation")
        raise
    return control, data_dir


def _validated_root(root: Path) -> Path:
    root = Path(root)
    try:
        mode = root.lstat().st_mode
    except FileNotFoundError as exc:
        raise BootstrapError("OpenDesign data root is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise BootstrapError("OpenDesign data root must be a real directory")
    return root.resolve(strict=True)


def _require_empty_real_directory(path: Path, *, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise BootstrapError(f"OpenDesign {label} directory is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise BootstrapError(f"OpenDesign {label} path must be a real directory")
    if any(path.iterdir()):
        raise BootstrapError(f"OpenDesign {label} directory is not empty")


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
