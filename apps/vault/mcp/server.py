"""Vault app MCP entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_operations import handle_operation


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    tool_name = str(payload.get("tool_name") or "")
    if tool_name != "maverick_vault":
        result = {
            "status_code": 404,
            "error": "unsupported_vault_tool",
            "detail": "Vault exposes only the maverick_vault redaction-safe agent operations tool.",
            "redaction_safe": True,
        }
    else:
        action = str(arguments.get("action") or "manifest").strip()
        result = handle_operation(payload, action=action)
        result["tool_name"] = tool_name
        result["supported_tools"] = ["maverick_vault"]
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
