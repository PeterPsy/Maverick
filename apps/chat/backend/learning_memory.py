"""Memory operations through the declared provider backend dependency."""

import json

from learning_store import audit, connection, new_id, now, settings
from learning_validation import normalize
from learning_reconciliation import current_review


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
    reviewed_revision = next((match.get("updated_at") for match in details.get("memory_matches", [])
                              if match.get("id") == target_node_id and match.get("updated_at")), None)
    confirmation = details.get("confirmation") or ("explicit_user_fact" if actor == "system" else "user_approved")
    sessions = list(dict.fromkeys(x["session_id"] for x in evidence))
    marks = ",".join("?" for _ in sessions)
    projects = {row[0] for row in db.execute(f"SELECT DISTINCT project_id FROM learning_conversations WHERE session_id IN ({marks})", sessions)} if sessions else set()
    project_id = next(iter(projects)) if len(projects) == 1 else ""
    source = "\n\n".join(f"Chat /app/chat/threads/{x['session_id']} · turn {x['turn_id']} · {x['role']}\n\n{x['quote']}" for x in evidence)
    if details.get("source_refs"):
        source += "\n\nCited references\n\n" + "\n".join(details["source_refs"])
    details.update(target_node_id=target_node_id, node_created=not bool(target_node_id), confirmation=confirmation)
    db.execute("UPDATE learning_items SET status='saving',operation_id=?,details=?,updated_at=? WHERE id=?",
               (token, json.dumps(details), now(), item["id"]))
    audit(db, "memory.save_requested", item["id"], actor)
    return dependency_request(item["id"], "learning.memory_saved", {
        "action": "ingest_source", "adapter_id": "inline_markdown",
        "source_key": "conversation-learning:" + item["id"], "title": item["title"],
        "summary": item["body"], "node_id": target_node_id, "node_type": "fact",
        "operation": "replace_fact" if target_node_id else "update_fact", "fact_body": item["body"], "fact_summary": item["body"],
        **({"expected_updated_at": reviewed_revision} if reviewed_revision else {}),
        "fact_metadata": {"knowledge_type": details.get("memory_type", ""), "confirmation": confirmation,
            "project_id": project_id, "candidate_id": item["id"], "chat_evidence": evidence},
        "confidence": details.get("confidence", 0.5), "compile_after_ingest": True,
        "body_markdown": source, "source": {"adapter_id": "inline_markdown",
            "source_key": "conversation-learning:" + item["id"], "body_markdown": source,
            "metadata": {"candidate_id": item["id"], "chat_evidence": evidence,
                "source_refs": details.get("source_refs", []), "knowledge_type": details.get("memory_type", ""),
                "confirmation": confirmation, "reviewed_at": item["updated_at"]}},
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
            details["memory_matches"] = [{"id": x.get("id", x.get("node_id", "")), "title": x.get("title", ""), "updated_at": x.get("updated_at", x.get("node", {}).get("updated_at", ""))}
                                          for x in matches if isinstance(x, dict)][:5]
            details["memory_check_error"] = "" if ok else "Memory provider unavailable; review before saving"
            provider = raw.get("dependency_provider_app_id") or item["provider_id"]
            db.execute("UPDATE learning_items SET status='pending',provider_id=?,details=?,updated_at=? WHERE id=?", (provider, json.dumps(details), now(), item["id"]))
            item = db.execute("SELECT * FROM learning_items WHERE id=?", (item["id"],)).fetchone()
            config = settings(db)
            evidence = json.loads(item["evidence"])
            # Auto mode is intentionally limited to verbatim explicit user facts.
            verbatim = bool(normalize(item["body"])) and any(normalize(item["body"]) in normalize(x["quote"]) for x in evidence)
            user_evidence = bool(evidence) and all(x["role"] == "user" for x in evidence)
            if ok and config["enabled"] and not config["paused"] and config["memory_enabled"] and config["memory_mode"] == "automatic" and not matches and details.get("explicit") is True and details.get("confidence", 0) >= .95 and verbatim and user_evidence and current_review(db, item):
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
        if normalize(node.get("body_text", "")) != normalize(item["body"]) or (details.get("target_node_id") and node["id"] != details["target_node_id"]):
            details["save_error"] = "Memory did not persist the approved fact; inspect the saved node before retrying"
            db.execute("UPDATE learning_items SET status='pending',details=?,updated_at=? WHERE id=?", (json.dumps(details), now(), item["id"]))
            audit(db, "memory.revision_verification_failed", item["id"])
            return {}
        details.update(node_updated_at=node.get("updated_at", ""), save_error="", saved_fact_verified=True)
        details["node_created"] = bool(result.get("node_created", details.get("node_created")))
        provider = raw.get("dependency_provider_app_id", "")
        db.execute("UPDATE learning_items SET status='saved',node_id=?,provider_id=?,details=?,updated_at=? WHERE id=?",
                   (node.get("id", ""), provider, json.dumps(details), now(), item["id"]))
        db.execute("UPDATE learning_implementations SET status='saved',error='',updated_at=? WHERE item_id=? AND status IN ('failed','cancelled')", (now(), item["id"]))
        audit(db, "memory.saved", item["id"])
        return {}
