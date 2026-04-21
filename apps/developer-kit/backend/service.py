"""Developer Kit backend service."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.packaging import package_app_source
from core.app_sdk.service import create_app_source, validate_app_source
from core.app_sdk.templates import SUPPORTED_TEMPLATES
from core.shared.repository import discover_repository_root


def handle_action(raw_payload: dict[str, object], body: dict[str, object]) -> tuple[int, dict[str, object]]:
    """Handle Developer Kit backend actions."""
    action = str(body.get("action") or "templates")
    repo_root = discover_repository_root(start_path=Path(__file__))
    workspace_id = str(body.get("workspace_id") or raw_payload.get("workspace_id") or "default")
    try:
        if action == "templates":
            return 200, {"templates": sorted(SUPPORTED_TEMPLATES)}
        if action == "create":
            request = AppSdkCreateRequest(
                app_id=str(body.get("app_id") or ""),
                template_id=str(body.get("template_id") or "minimal"),
                target_kind="workspace_local",
                workspace_id=workspace_id,
                name=_optional_string(body.get("name")),
                description=_optional_string(body.get("description")),
                publisher=str(body.get("publisher") or "workspace"),
                entities=[str(entity) for entity in body.get("entities", [])] if isinstance(body.get("entities"), list) else None,
                overwrite=bool(body.get("overwrite", False)),
            )
            return 201, asdict(create_app_source(request, start_path=repo_root))
        if action == "validate":
            app_id = str(body.get("app_id") or "")
            app_root = repo_root / "workspaces" / workspace_id / "apps" / app_id
            return 200, asdict(validate_app_source(app_root))
        if action == "package":
            app_id = str(body.get("app_id") or "")
            app_root = repo_root / "workspaces" / workspace_id / "apps" / app_id
            output_path = repo_root / "workspaces" / workspace_id / "storage" / "generated" / f"{app_id}.tar.gz"
            return 201, asdict(package_app_source(app_root, output_path=output_path))
    except Exception as error:
        return 400, {"error": "developer_kit_error", "detail": str(error)}
    return 400, {"error": "unsupported_action", "detail": f"Unsupported action `{action}`."}


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
