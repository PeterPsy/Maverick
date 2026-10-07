"""Exact approved Memory writes from the candidate's own implementation chat."""

import json

from learning_memory import save_request
from learning_store import connection


def memory_agent_action(payload):
    body = payload.get("body", {})
    if payload.get("surface") != "mcp" or not payload.get("runtime_session_id"):
        raise PermissionError("This operation requires the approved Memory work chat")
    with connection(payload["data_root"], write=True) as db:
        item = db.execute("SELECT * FROM learning_items WHERE id=? AND kind='memory'", (body.get("item_id", ""),)).fetchone()
        ticket = db.execute("SELECT * FROM learning_implementations WHERE item_id=? AND session_id=?",
                            (body.get("item_id", ""), payload["runtime_session_id"])).fetchone()
        if not item or not ticket:
            raise PermissionError("Memory candidate is not approved for this chat")
        receipt = {"item_id": item["id"], "status": item["status"], "node_id": item["node_id"], "provider_id": item["provider_id"]}
        if item["node_id"]:
            receipt["deep_link"] = "/app/" + item["provider_id"] + "/nodes/" + item["node_id"]
        if body.get("command") == "inspect":
            return receipt
        if body.get("command") != "commit":
            raise ValueError("Use inspect or commit")
        if item["status"] in {"saved", "saving"}:
            return receipt
        if ticket["status"] != "running" or item["status"] not in {"accepted", "pending"}:
            raise ValueError("Memory implementation is not active or was stopped")
        target = json.loads(item["details"]).get("target_node_id", "")
        request = save_request(db, item, target_node_id=target, actor=ticket["actor"])
        return {**receipt, "status": "saving", "dependency_backend_requests": [request], "_changed": True}
