"""Memory app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from errors import MemoryValidationError
from service import handle_action


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    try:
        status_code, result = handle_action(Path(payload["data_root"]), body)
    except MemoryValidationError as error:
        status_code, result = 400, {"error": "validation_error", "detail": str(error)}
    print(json.dumps({"status_code": status_code, "json": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()

