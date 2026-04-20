"""Skills app backend entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from service import handle_action
from store import SkillsValidationError


def _response(status_code: int, payload: dict) -> None:
    print(json.dumps({"status_code": status_code, "json": payload}, ensure_ascii=False))


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    data_root = Path(payload["data_root"])
    agent_skill_roots = payload.get("agent_skill_roots") if isinstance(payload.get("agent_skill_roots"), list) else None
    try:
        status_code, result = handle_action(data_root, body, agent_skill_roots=agent_skill_roots)
    except SkillsValidationError as error:
        _response(400, {"error": "validation_error", "detail": str(error)})
        return
    _response(status_code, result)


if __name__ == "__main__":
    main()
