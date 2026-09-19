"""Authority comes from the Core envelope, never from operation arguments."""
from dataclasses import dataclass

from .errors import AppError


@dataclass(frozen=True)
class Context:
    workspace_id: str
    user_id: str = ""
    workspace_role: str = ""
    platform_role: str = ""
    surface: str = ""
    runtime_session_id: str = ""
    provider_id: str = ""

    def require_user(self, *, admin=False):
        if not self.workspace_id or not self.user_id:
            raise AppError("authentication_required", 403)
        if admin and self.platform_role != "admin" and self.workspace_role not in {"admin", "owner"}:
            raise AppError("admin_required", 403)
        if self.platform_role != "admin" and self.workspace_role not in {"admin", "owner", "member"}:
            raise AppError("workspace_permission_denied", 403)

    def require_human(self):
        self.require_user(admin=True)
        if self.surface != "backend" or self.runtime_session_id:
            raise AppError("human_ui_confirmation_required", 403)


def selected_provider(dependencies):
    if not isinstance(dependencies, dict):
        return ""
    for item in dependencies.get("dependencies", []):
        if item.get("alias") == "static-exporter" and item.get("status") == "resolved":
            ids = item.get("selected_provider_app_ids", [])
            if len(ids) == 1 and isinstance(ids[0], str):
                return ids[0]
    return ""


def from_envelope(payload):
    return Context(
        workspace_id=str(payload.workspace_id or ""), user_id=str(payload.user_id or ""),
        workspace_role=str(payload.workspace_role or ""), platform_role=str(payload.platform_role or ""),
        surface=str(payload.raw.get("surface") or ""), runtime_session_id=str(payload.runtime_session_id or ""),
        provider_id=selected_provider(payload.raw.get("app_dependencies", {})),
    )
