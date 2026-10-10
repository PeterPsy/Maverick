"""Connectors official MCP entrypoint."""
from pathlib import Path
import sys
from core.app_sdk.runtime import emit_json, read_entrypoint_payload
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from service import handle
payload = read_entrypoint_payload()
body = dict(payload.arguments)
name = str(payload.raw.get("tool_name") or "")
body["action"] = "references."+name.removeprefix("platform_connectors_reference_") if name.startswith("platform_connectors_reference_") else name.removeprefix("platform_connectors_") if name.startswith("platform_connectors_") else name.removeprefix("connectors_").replace("_", ".", 1)
status,result = handle(payload,body)
result["status_code"] = status
emit_json(result)
