"""Memory operations through the declared provider backend dependency."""

import json

from learning_store import audit, connection, new_id, now, settings
from learning_validation import normalize


def dependency_request(item_id, callback, body, *, operation_id="", provider_id=""):
    request = {"dependency_alias": "learning-memory", "request_id": new_id("memory_request"), "body": body,
               "callback": {"action": callback, "payload": {"item_id": item_id, "operation_id": operation_id}}}
    if provider_id:
        request["provider_app_id"] = provider_id
    return request


def save_request(db, item, *, target_node_id="", actor="system"):
    token = new_id("memory_operation")
    details = json.loads(item["details"])
    evidence = json.loads(item["evidence"])
    source = "\n\n".join(f"Chat /app/chat/threads/{x['session_id']} · turn {x['turn_id']} · {x['role']}\n\n{x['quote']}" for x in evidence)
    details.update(target_node_id=target_node_id, node_created=not bool(target_node_id))
    db.execute("UPDATE learning_items SET status='saving',operation_id=?,details=?,updated_at=? WHERE id=?",
               (token, json.dumps(details), now(), item["id"]))
    audit(db, "memory.save_requested", item["id"], actor)
    return dependency_request(item["id"], "learning.memory_saved", {
        "action": "ingest_source", "adapter_id": "inline_markdown",
        "source_key": "conversation-learning:" + item["id"], "title": item["title"],
        "summary": item["body"], "node_id": target_node_id, "node_type": "fact",
        "confidence": details.get("confidence", 0.5), "compile_after_ingest": True,
        "body_markdown": source, "source": {"adapter_id": "inline_markdown",
            "source_key": "conversation-learning:" + item["id"], "body_markdown": source,
            "metadata": {"candidate_id": item["id"], "chat_evidence": evidence}},
    }, operation_id=token, provider_id=item["provider_id"])


def memory_callback(data_root, body):
    action = body["action"]
    with connection(data_root, write=True) as db:
        item = db.execute("SELECT * FROM learning_items WHERE id=?", (body.get("item_id", ""),)).fetchone()
        if not item:
            return {"ignored": True}
        raw = body.get("dependency_backend_result", {})
        result = raw.get("json", {}) if isinstance(raw, dict) else {}
        ok = body.get("dependency_backend_status") == "completed" and int(raw.get("status_code", 500)) < 400
        if action == "learning.memory_checked":
            if item["status"] != "checking" or item["operation_id"] != body.get("operation_id"):
                return {"ignored": True}
            matches = result.get("results", []) if ok else []
            details = json.loads(item["details"])
            details["memory_matches"] = [{"id": x.get("id", x.get("node_id", "")), "title": x.get("title", "")}
                                          for x in matches if isinstance(x, dict)][:5]
            details["memory_check_error"] = "" if ok else "Memory provider unavailable; review before saving"
            provider = raw.get("dependency_provider_app_id") or item["provider_id"]
            db.execute("UPDATE learning_items SET status='pending',provider_id=?,details=?,updated_at=? WHERE id=?", (provider, json.dumps(details), now(), item["id"]))
            item = db.execute("SELECT * FROM learning_items WHERE id=?", (item["id"],)).fetchone()
            config = settings(db)
            evidence = json.loads(item["evidence"])
            # Auto mode is intentionally limited to verbatim explicit user facts.
            verbatim = bool(normalize(item["body"])) and any(normalize(item["body"]) in normalize(x["quote"]) for x in evidence)
            if ok and config["enabled"] and not config["paused"] and config["memory_enabled"] and config["memory_mode"] == "automatic" and not matches and details.get("explicit") is True and details.get("confidence", 0) >= .95 and verbatim:
                return {"dependency_backend_requests": [save_request(db, item)]}
            return {}
        if item["operation_id"] != body.get("operation_id") or item["status"] not in {"saving", "undoing"}:
            return {"ignored": True}
        details = json.loads(item["details"])
        if not ok:
            details["save_error"] = "Memory operation failed; retry from Settings"
            db.execute("UPDATE learning_items SET status=?,details=?,updated_at=? WHERE id=?",
                       ("saved" if item["status"] == "undoing" else "pending", json.dumps(details), now(), item["id"]))
            audit(db, "memory.operation_failed", item["id"])
            return {}
        if action == "learning.memory_undone":
            db.execute("UPDATE learning_items SET status='undone',updated_at=? WHERE id=?", (now(), item["id"]))
            audit(db, "memory.undone", item["id"])
            return {}
        node = result.get("node", {})
        if not isinstance(node, dict) or not node.get("id") or not node.get("updated_at"):
            raise ValueError("Memory provider returned no saved node revision")
        details.update(node_updated_at=node.get("updated_at", ""), save_error="")
        provider = raw.get("dependency_provider_app_id", "")
        db.execute("UPDATE learning_items SET status='saved',node_id=?,provider_id=?,details=?,updated_at=? WHERE id=?",
                   (node.get("id", ""), provider, json.dumps(details), now(), item["id"]))
        audit(db, "memory.saved", item["id"])
        return {}
