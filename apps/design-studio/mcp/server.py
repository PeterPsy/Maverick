"""MCP entrypoint for Design Studio."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from core.app_sdk.runtime import emit_json, read_entrypoint_payload
from service import DesignStudioError, dispatch


TOOL_ACTIONS = {
    "design_studio_state": "state",
    "design_studio_get_project": "get_project",
    "design_studio_import_from_storage": "import_from_storage",
    "design_studio_export_to_storage": "export_to_storage",
    "design_studio_view_filter": "view_filter",
    "design_studio_set_view_filter": "set_view_filter",
    "design_studio_set_custom_view": "set_custom_view",
    "design_studio_clear_custom_view": "clear_custom_view",
    "design_studio_reference_manifest": "reference_manifest",
    "design_studio_reference_search": "reference_search",
    "design_studio_reference_resolve": "reference_resolve",
    "design_studio_reference_summarize": "reference_summarize",
}


def main() -> None:
    payload = read_entrypoint_payload()
    tool_name = str(payload.raw.get("tool_name") or "design_studio_state")
    action = TOOL_ACTIONS.get(tool_name)
    if action is None:
        emit_json({"ok": False, "error": "unsupported_tool", "detail": f"Unsupported Design Studio tool `{tool_name}`."})
        return
    try:
        result = dispatch(action, payload.raw, dict(payload.arguments))
    except DesignStudioError as error:
        emit_json({"ok": False, "error": error.error, "detail": error.detail})
        return
    emit_json({"ok": True, **result})


if __name__ == "__main__":
    main()
