"""Render only OpenDesign's supported technical local-agent profile file."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from model_access_client import ModelAccessClient
from model_access_constants import MODEL_ACCESS_API_KEY, MODEL_ACCESS_BASE_URL


PROFILE_PATH = Path("sandbox/agent-home/.maverick/model-access-agents.json")
SANDBOX_PROFILE_PATH = Path("/data/opendesign-native") / PROFILE_PATH
API_CONFIG_PATH = Path("sandbox/agent-home/.maverick/model-access-opencode.json")
SANDBOX_API_CONFIG_PATH = Path("/data/opendesign-native") / API_CONFIG_PATH
CODEX_WRAPPER = "maverick-codex"
OPENCODE_WRAPPER = "maverick-opencode"
API_PROFILE_ID = "installed-maverick-api"
API_PROVIDER_ID = "maverick"


def write_model_access_profiles(data_dir: Path, client: ModelAccessClient) -> tuple[Path, dict[str, object]]:
    catalog = client.catalog()
    raw_cli_models = catalog.get("cli_models")
    cli_models = [
        {"id": item["id"], "label": item.get("label") or item["id"]}
        for item in raw_cli_models or []
        if isinstance(item, dict)
        and item.get("provider_id") == "codex"
        and item.get("available") is True
        and isinstance(item.get("id"), str)
    ]
    raw_api_models = catalog.get("api_models")
    api_models = [
        {
            "id": f"{API_PROVIDER_ID}/{item['id']}",
            "label": item.get("label") or item["id"],
        }
        for item in raw_api_models or []
        if isinstance(item, dict)
        and item.get("transport") == "api"
        and item.get("available") is True
        and isinstance(item.get("id"), str)
        and item["id"]
    ]
    if not cli_models:
        raise RuntimeError("No configured Codex CLI model is available")
    if not api_models:
        raise RuntimeError("No configured API model is available")
    defaults = catalog.get("cli_defaults") if isinstance(catalog.get("cli_defaults"), dict) else {}
    default_cli_model = (
        defaults.get("codex")
        if isinstance(defaults.get("codex"), str)
        else cli_models[0]["id"]
    )
    default_api_model = api_models[0]["id"]
    api_config = {
        "provider": {
            API_PROVIDER_ID: {
                "name": "Maverick Model Access",
                "npm": "@ai-sdk/openai-compatible",
                "options": {
                    "baseURL": MODEL_ACCESS_BASE_URL,
                    "apiKey": MODEL_ACCESS_API_KEY,
                },
                "models": {
                    item["id"].removeprefix(f"{API_PROVIDER_ID}/"): {
                        "name": item["label"],
                    }
                    for item in api_models
                },
            }
        }
    }
    payload = {
        "agents": [
            {
                "id": "installed-codex-cli",
                "name": "Codex CLI (installed)",
                "baseAgent": "codex",
                "bin": CODEX_WRAPPER,
                "models": cli_models,
                "defaultModel": default_cli_model,
            },
            {
                "id": API_PROFILE_ID,
                "name": "Maverick API models",
                "baseAgent": "opencode",
                "bin": OPENCODE_WRAPPER,
                "env": {
                    "OPENCODE_CONFIG": SANDBOX_API_CONFIG_PATH.as_posix(),
                    "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
                },
                "models": api_models,
                "defaultModel": default_api_model,
            },
        ]
    }
    _atomic_json(data_dir / API_CONFIG_PATH, api_config)
    target = data_dir / PROFILE_PATH
    _atomic_json(target, payload)
    return target, {
        "profile_id": "installed-codex-cli",
        "model_count": len(cli_models),
        "default_model": default_cli_model,
        "api_profile_id": API_PROFILE_ID,
        "api_model_count": len(api_models),
        "api_default_model": default_api_model,
        "total_model_count": len(cli_models) + len(api_models),
    }


def remove_model_access_profiles(data_dir: Path) -> None:
    for relative in (PROFILE_PATH, API_CONFIG_PATH):
        target = data_dir / relative
        try:
            metadata = target.lstat()
            if stat.S_ISREG(metadata.st_mode):
                target.unlink()
        except FileNotFoundError:
            continue


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
