"""Document Generator app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import DocumentValidationError
from service import app_events_for_result, handle_action


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
tool_actions = {
    "document_generator_convert_to_markdown": "convert_to_markdown",
    "document_generator_extract_text": "extract_text",
    "document_generator_patch_pdf_text": "patch_pdf_text",
    "document_generator_modify_uploaded_document": "modify_uploaded_document",
    "document_generator_spreadsheet_transform": "spreadsheet.transform",
    "document_generator_reference_manifest": "references.manifest",
    "document_generator_reference_search": "references.search",
    "document_generator_reference_resolve": "references.resolve",
    "document_generator_reference_summarize": "references.summarize",
    "document_generator_view_filter": "view_filter",
    "document_generator_set_view_filter": "set_view_filter",
    "document_generator_set_custom_view": "set_custom_view",
    "document_generator_clear_custom_view": "clear_custom_view",
}
tool_name = str(payload.get("tool_name") or "")
body = dict(arguments)
mapped_action = tool_actions.get(tool_name)
if mapped_action is None:
    body.setdefault("action", "generate_document")
else:
    body["action"] = mapped_action
try:
    uploaded_root = Path(payload["uploaded_storage_root"]) if payload.get("uploaded_storage_root") else None
    status_code, result = handle_action(
        Path(payload["data_root"]),
        Path(payload["generated_storage_root"]),
        body,
        uploaded_root,
        local_app_id=str(payload.get("app_id") or "document-generator"),
    )
except DocumentValidationError as error:
    status_code, result = 400, {"error": "validation_error", "detail": str(error)}

response = {"status_code": status_code, **result}
if status_code < 400:
    response["app_events"] = app_events_for_result(str(body.get("action") or "generate_document"), result)
print(json.dumps(response, ensure_ascii=False))
