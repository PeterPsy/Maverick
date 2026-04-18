import json
from pathlib import Path
import sys
from uuid import uuid4


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


payload = json.loads(sys.stdin.read() or "{}")
data_root = Path(payload["data_root"])
messages_path = data_root / "conversations.json"
state = _read_json(messages_path)
messages = state.get("messages", [])
action = payload.get("body", {}).get("action", "bootstrap")
runtime_session_id = payload.get("runtime_session_id")
provider_id = payload.get("provider_id", "codex")

if not messages:
    messages = [
        {
            "id": str(uuid4()),
            "role": "assistant",
            "content": "Chat smoke app is mounted. The core is routing frontend, backend, CLI, MCP, and workspace storage."
        }
    ]

if action == "send":
    user_message = str(payload.get("body", {}).get("message", "")).strip()
    if user_message:
        messages.append({"id": str(uuid4()), "role": "user", "content": user_message})
        messages.append(
            {
                "id": str(uuid4()),
                "role": "assistant",
                "content": (
                    f"Echo from chat app. Workspace `{payload['workspace_id']}` is mounted correctly, "
                    f"provider `{provider_id}` is selected, runtime session `{runtime_session_id}` exists, "
                    f"and app-owned storage lives under `{data_root}`."
                ),
            }
        )

_write_json(
    messages_path,
    {
        "messages": messages,
        "last_runtime_session_id": runtime_session_id,
        "last_provider_id": provider_id,
    },
)

print(
    json.dumps(
        {
            "status_code": 200,
            "json": {
                "workspace_id": payload["workspace_id"],
                "app_id": payload["app_id"],
                "provider_id": provider_id,
                "runtime_session_id": runtime_session_id,
                "messages": messages,
            },
        }
    )
)
