"""Storage app MCP entrypoint."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from mcp_requests import handle_payload


if __name__ == "__main__":
    print(json.dumps(handle_payload(json.loads(sys.stdin.read() or "{}")), ensure_ascii=False))
