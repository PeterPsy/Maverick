"""Render only OpenDesign's supported technical local-agent profile file."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from model_access_client import ModelAccessClient


PROFILE_PATH = Path("sandbox/agent-home/.maverick/model-access-agents.json")
SANDBOX_PROFILE_PATH = Path("/data/opendesign-native") / PROFILE_PATH
CODEX_WRAPPER = "maverick-codex"


def write_model_access_profiles(data_dir: Path, client: ModelAccessClient) -> tuple[Path, dict[str, object]]:
    catalog = client.catalog()
    raw_models = catalog.get("cli_models")
    models = [
        {"id": item["id"], "label": item.get("label") or item["id"]}
        for item in raw_models or []
        if isinstance(item, dict)
        and item.get("provider_id") == "codex"
        and item.get("available") is True
        and isinstance(item.get("id"), str)
    ]
    if not models:
        raise RuntimeError("No configured Codex CLI model is available")
    defaults = catalog.get("cli_defaults") if isinstance(catalog.get("cli_defaults"), dict) else {}
    default_model = defaults.get("codex") if isinstance(defaults.get("codex"), str) else models[0]["id"]
    payload = {
        "agents": [
            {
                "id": "installed-codex-cli",
                "name": "Codex CLI (installed)",
                "baseAgent": "codex",
                "bin": CODEX_WRAPPER,
                "models": models,
                "defaultModel": default_model,
            }
        ]
    }
    target = data_dir / PROFILE_PATH
    _atomic_json(target, payload)
    return target, {
        "profile_id": "installed-codex-cli",
        "model_count": len(models),
        "default_model": default_model,
    }


def remove_model_access_profiles(data_dir: Path) -> None:
    target = data_dir / PROFILE_PATH
    try:
        metadata = target.lstat()
        if stat.S_ISREG(metadata.st_mode):
            target.unlink()
    except FileNotFoundError:
        return


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.write(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
