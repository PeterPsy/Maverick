"""Trusted administrator operations for the existing local OpenWA provider."""
from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "provider"))
sys.path.insert(0, str(APP_ROOT / "backend"))
from provider_service import ProviderServiceError, operate


def handle_provider(payload):
    if not payload.user_id or payload.platform_role != "admin" or payload.workspace_id != "default":
        return {"ok": False, "error": "provider_admin_required", "status_code": 403}
    expected = APP_ROOT.parents[1] / "workspaces/default/data/openwa"
    if Path(payload.data_root).resolve() != expected.resolve():
        return {"ok": False, "error": "provider_scope_mismatch", "status_code": 403}
    try:
        return operate(payload.arguments.get("action", "status"))
    except (ProviderServiceError, OSError) as error:
        detail = str(error) if isinstance(error, ProviderServiceError) else "The provider service could not be reached."
        return {"ok": False, "error": "provider_service_failed", "detail": detail, "status_code": 503}


if __name__ == "__main__":
    emit_json(handle_provider(read_entrypoint_payload()))
