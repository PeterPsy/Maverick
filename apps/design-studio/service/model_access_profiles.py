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


def write_model_access_profiles(
    data_dir: Path,
    client: ModelAccessClient,
    *,
    opencode_available: bool = True,
    api_unavailable_reason: str = "opencode_runtime_unavailable",
) -> tuple[Path, dict[str, object]]:
    """Write every independently usable native agent profile.

    A missing catalog or technical runtime removes only the affected profile.
    At least one usable profile is required for a profile file to be published.
    """
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
    defaults = catalog.get("cli_defaults") if isinstance(catalog.get("cli_defaults"), dict) else {}
    agents: list[dict[str, object]] = []
    if cli_models:
        default_cli_model = (
            defaults.get("codex")
            if isinstance(defaults.get("codex"), str)
            and any(item["id"] == defaults["codex"] for item in cli_models)
            else cli_models[0]["id"]
        )
        agents.append(
            {
                "id": "installed-codex-cli",
                "name": "Codex CLI (installed)",
                "baseAgent": "codex",
                "bin": CODEX_WRAPPER,
                "models": cli_models,
                "defaultModel": default_cli_model,
            }
        )
        cli_status: dict[str, object] = {
            "state": "ready",
            "profile_id": "installed-codex-cli",
            "model_count": len(cli_models),
            "default_model": default_cli_model,
        }
    else:
        default_cli_model = None
        cli_status = {
            "state": "degraded",
            "reason": "no_configured_cli_models",
            "model_count": 0,
        }

    if api_models and opencode_available:
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
        _atomic_json(data_dir / API_CONFIG_PATH, api_config)
        agents.append(
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
            }
        )
        api_status: dict[str, object] = {
            "state": "ready",
            "profile_id": API_PROFILE_ID,
            "model_count": len(api_models),
            "default_model": default_api_model,
        }
    else:
        default_api_model = None
        _remove_regular_file(data_dir / API_CONFIG_PATH)
        api_status = {
            "state": "degraded",
            "reason": (
                api_unavailable_reason
                if api_models and not opencode_available
                else "no_configured_api_models"
            ),
            "model_count": len(api_models),
        }

    if not agents:
        _remove_regular_file(data_dir / PROFILE_PATH)
        raise RuntimeError("No configured native model profile is available")
    payload = {"agents": agents}
    target = data_dir / PROFILE_PATH
    _atomic_json(target, payload)
    return target, {
        "state": (
            "ready"
            if cli_status["state"] == api_status["state"] == "ready"
            else "degraded"
        ),
        "profile_count": len(agents),
        "profile_id": "installed-codex-cli" if cli_models else None,
        "model_count": len(cli_models),
        "default_model": default_cli_model,
        "api_profile_id": API_PROFILE_ID if api_status["state"] == "ready" else None,
        "api_model_count": len(api_models),
        "api_default_model": default_api_model,
        "total_model_count": sum(len(profile["models"]) for profile in agents),
        "cli": cli_status,
        "api": api_status,
    }


def remove_model_access_profiles(data_dir: Path) -> None:
    for relative in (PROFILE_PATH, API_CONFIG_PATH):
        _remove_regular_file(data_dir / relative)


def _remove_regular_file(target: Path) -> None:
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
