"""Actor-scoped Scheduled tasks operations shared by backend, CLI and MCP."""

import json

from scheduled_controls import control
from scheduled_notifications import notifications
from scheduled_runtime import persist_request, reference, runtime_event, runtime_request, started
from scheduled_store import connection, new_id, now, open_run, owned_chat, project_chat
from scheduled_tick import tick
from scheduled_validation import ID, next_due, text, validate_config

PUBLIC_ACTIONS = {"scheduled." + name for name in (
    "list", "read", "create", "update", "delete", "pause", "resume", "run", "continue", "retry", "cancel", "initialize")}


def management_request(db, chat):
    config = json.loads(chat["config"])
    prompt = ("This is the management conversation for a Scheduled task. Initialize it by briefly confirming it is ready. "
              "Do not execute any blocks now. When the user asks to create or edit blocks, use the chat_scheduled MCP tool "
              "(or loopino app chat cli run scheduled) with action read, then update with expected_revision and the complete graph. "
              "A graph has nodes {id,title,instructions,skill_ids,position:{x,y}} and edges {id,source,target}. "
              "Connections are prerequisites and must form a DAG. Every successful block stops at a checkpoint; "
              "only the user's explicit confirmation may continue it. Keep all UI titles and labels in English. "
              "Read current state before editing; do not run, confirm, delete or reschedule without a user request.\n" +
              json.dumps({"scheduled_chat_id": chat["id"], "title": config["title"], "goal": config["instructions"]}, ensure_ascii=False))
    request = runtime_request(chat, request_id=new_id(), input_text=prompt, kind="message")
    persist_request(db, chat, request, kind="message")
    return request


def handle_scheduled(payload):
    root, body, surface = payload["data_root"], payload.get("body", {}), payload.get("surface", "")
    action = body.get("action", "")
    if surface in {"background_tick", "backend_recovery"}:
        return tick(root, body)
    if surface == "runtime_event":
        with connection(root, write=True) as db:
            return runtime_event(db, body)
    if action == "scheduled.started":
        if surface != "runtime_request_callback":
            raise PermissionError("Trusted runtime callback required")
        with connection(root, write=True) as db:
            return started(db, body)
    actor = payload.get("user_id")
    if not isinstance(actor, str) or not actor:
        raise PermissionError("Scheduled tasks require an authenticated actor")
    with connection(root, write=action not in {"scheduled.list", "scheduled.read", "notifications.list"}) as db:
        if action.startswith("notifications."):
            return notifications(db, body, actor)
        if action not in PUBLIC_ACTIONS:
            raise ValueError("Unknown scheduled-task operation")
        if action not in {"scheduled.list", "scheduled.read"}:
            worker = db.execute("SELECT 1 FROM scheduled_requests WHERE kind='block' AND session_id=? AND session_id!=''", (payload.get("runtime_session_id", ""),)).fetchone()
            if worker:
                raise PermissionError("A skill block cannot modify schedules or confirm its own checkpoint")
        if action == "scheduled.list":
            query = text(body.get("query", ""), "Search", 200, optional=True).casefold()
            rows = db.execute("SELECT * FROM scheduled_chats WHERE owner=? AND deleted=0 ORDER BY updated_at DESC LIMIT 500", (actor,))
            items = [project_chat(db, row) for row in rows]
            return {"chats": [item for item in items if query in item["title"].casefold() or query in item["instructions"].casefold()]}
        if action == "scheduled.create":
            chat_id = body.get("creation_id") or new_id()
            if not isinstance(chat_id, str) or not ID.fullmatch(chat_id):
                raise ValueError("Invalid creation id")
            existing = db.execute("SELECT * FROM scheduled_chats WHERE id=?", (chat_id,)).fetchone()
            if existing:
                return {"chat": project_chat(db, owned_chat(db, chat_id, actor), detail=True)}
            if db.execute("SELECT COUNT(*) FROM scheduled_chats WHERE owner=? AND deleted=0", (actor,)).fetchone()[0] >= 500:
                raise ValueError("Scheduled task limit reached")
            config = validate_config(body)
            due = next_due(config["schedule"], now())
            if config["schedule"]["frequency"] == "once" and due is None:
                raise ValueError("Choose a future date and time")
            db.execute("INSERT INTO scheduled_chats(id,owner,config,next_due,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                       (chat_id, actor, json.dumps(config), due, now(), now()))
            chat = owned_chat(db, chat_id, actor)
            request = management_request(db, chat)
            return {"chat": project_chat(db, chat, detail=True), "runtime_session_requests": [request], "_scheduled_changed": True}
        chat = owned_chat(db, body.get("chat_id", ""), actor)
        if action == "scheduled.read":
            return {"chat": project_chat(db, chat, detail=True)}
        if action == "scheduled.update":
            expected = body.get("expected_revision")
            if not isinstance(expected, int) or isinstance(expected, bool) or expected != chat["revision"]:
                raise ValueError("This scheduled task changed. Reload before saving.")
            if open_run(db, chat["id"]):
                raise ValueError("Finish or cancel the current run before editing its graph or schedule")
            config = validate_config(body, json.loads(chat["config"]))
            due = next_due(config["schedule"], now())
            if config["schedule"]["frequency"] == "once" and due is None:
                raise ValueError("Choose a future date and time")
            db.execute("UPDATE scheduled_chats SET config=?,revision=revision+1,next_due=?,updated_at=? WHERE id=?",
                       (json.dumps(config), due, now(), chat["id"]))
            result = {"_scheduled_changed": True}
        elif action == "scheduled.initialize":
            if chat["chat_session_id"]:
                return {"chat": project_chat(db, chat, detail=True)}
            pending = db.execute("SELECT * FROM scheduled_requests WHERE chat_id=? AND kind='message' ORDER BY updated_at DESC LIMIT 1", (chat["id"],)).fetchone()
            if pending and pending["status"] in {"queued", "launching", "running"}:
                result = {"runtime_session_requests": [json.loads(pending["request_json"])]}
            else:
                result = {"runtime_session_requests": [management_request(db, chat)]}
            result["_scheduled_changed"] = True
        else:
            result = control(db, chat, body)
        if action != "scheduled.delete":
            result["chat"] = project_chat(db, owned_chat(db, chat["id"], actor), detail=True)
        return result


def scheduled_references(payload):
    actor, body = payload.get("user_id"), payload.get("body", {})
    if not actor:
        raise PermissionError("Scheduled task references require an authenticated actor")
    action = body["action"]
    with connection(payload["data_root"]) as db:
        if action == "references.search":
            query = str(body.get("query", body.get("q", ""))).casefold()[:200]
            limit = body.get("limit", 10)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
                raise ValueError("Limit must be 1–50")
            rows = db.execute("SELECT * FROM scheduled_chats WHERE owner=? AND deleted=0 ORDER BY updated_at DESC LIMIT 500", (actor,))
            items = [reference_item(row) for row in rows]
            return {"results": [item for item in items if query in item["title"].casefold() or query in item["summary"].casefold()][:limit]}
        chat_id = body.get("entity_id") or body.get("id") or ""
        row = db.execute("SELECT * FROM scheduled_chats WHERE id=? AND owner=? AND deleted=0", (chat_id, actor)).fetchone()
        if not row:
            return {"exists": False, "app_id": "chat", "entity_type": "scheduled_chat", "entity_id": chat_id}
        return {"exists": True, **reference_item(row)}


def reference_item(row):
    config = json.loads(row["config"])
    return {**reference(row), "title": config["title"], "subtitle": "Scheduled task", "confidence": 1.0,
            "app_page": "scheduled/" + row["id"], "summary": config["instructions"][:500] or "Scheduled skill-block graph. Read and manage it with chat_scheduled.",
            "safe_fields": {"title": config["title"], "revision": row["revision"]}}
