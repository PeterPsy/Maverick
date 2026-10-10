"""Connectors official CLI entrypoint."""
from pathlib import Path
import sys
from core.app_sdk.runtime import emit_json, read_entrypoint_payload
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from service import handle
payload = read_entrypoint_payload()
body = dict(payload.arguments)
body.setdefault("action","status")
status,result = handle(payload,body)
result["status_code"] = status
emit_json(result)
