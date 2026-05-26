"""Vault app CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_operations import handle_operation


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    action = str(arguments.get("action") or "manifest").strip()
    print(json.dumps(handle_operation(payload, action=action), ensure_ascii=False))


if __name__ == "__main__":
    main()
