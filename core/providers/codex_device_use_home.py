"""Filesystem isolation for Codex sessions that proxy the native Mac."""

from __future__ import annotations

from pathlib import Path

from core.device_use.contract import DEVICE_USE_CODEX_CONFIG


def device_use_workdir(session, runtime_root: Path) -> Path:
    if getattr(session, "device_use_binding", None) is None:
        return Path(session.workdir)
    workdir = runtime_root / "device-work"
    workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return workdir


def prepare_device_use_runtime_home(owner, session, runtime_home: Path) -> bool:
    if getattr(session, "device_use_binding", None) is None:
        return False
    for name in ("rules", "skills"):
        owner._reset_path(runtime_home / name)
    (runtime_home / "config.toml").write_text(DEVICE_USE_CODEX_CONFIG, encoding="utf-8")
    owner._remove_disabled_runtime_material(runtime_home)
    return True
