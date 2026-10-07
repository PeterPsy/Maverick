"""Bounded episode history, outstanding work and existing proposals for review."""

import json


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def exchange(row):
    item = dict(row)
    item["metrics"] = json.loads(item["metrics"])
    return item


def build_input(db, job, config, *, memory_provider_app_id=""):
    excluded_sources = set(config["excluded_thread_ids"])
    excluded_sources.update(row["session_id"] for row in db.execute("SELECT session_id,project_id FROM learning_conversations")
                            if row["project_id"] in config["excluded_project_ids"])
    state = db.execute("SELECT * FROM learning_context WHERE session_id=?", (job["session_id"],)).fetchone()
    episode = json.loads(state["episode_json"]) if state else {}
    episode = {"status": episode.get("status", "uncertain"), "summary": episode.get("summary", "")[:1000],
               "open_work": [x[:150] for x in episode.get("open_work", [])[:4]]}
    result = {"session_id": job["session_id"], "exchanges": [], "prior_context": [],
              "memory_enabled": config["memory_enabled"], "improvements_enabled": config["improvements_enabled"],
              "memory_provider_app_id": memory_provider_app_id,
              "source_revisions": {job["session_id"]: state["latest_turn_id"] if state else ""},
              "episode_state": {key: episode[key] for key in ("status", "summary", "open_work") if key in episode},
              "current_work": [], "existing_items": []}
    for row in db.execute("""SELECT c.session_id,c.project_id,x.current_input FROM learning_conversations c
        JOIN learning_context x ON x.session_id=c.session_id WHERE c.busy=1 AND c.session_id!=?
        ORDER BY c.last_activity DESC LIMIT 8""", (job["session_id"],)):
        if row["session_id"] in config["excluded_thread_ids"] or row["project_id"] in config["excluded_project_ids"]:
            continue
        result["current_work"].append({"session_id": row["session_id"], "request": row["current_input"][:700]})
    for row in db.execute("""SELECT i.*,t.status AS implementation_status FROM learning_items i
        LEFT JOIN learning_implementations t ON t.item_id=i.id
        ORDER BY EXISTS(SELECT 1 FROM learning_item_sources s WHERE s.item_id=i.id AND s.session_id=?) DESC,
        i.updated_at DESC LIMIT 20""", (job["session_id"],)):
        sources = sorted({x[0] for x in db.execute("SELECT session_id FROM learning_item_sources WHERE item_id=?", (row["id"],))}
                         | {x["session_id"] for x in json.loads(row["evidence"])})
        if excluded_sources.intersection(sources):
            continue
        details = json.loads(row["details"])
        result["existing_items"].append({"id": row["id"], "kind": row["kind"], "title": row["title"],
            "body": row["body"][:600], "status": row["status"], "implementation_status": row["implementation_status"],
            "discarded_by_user": bool(details.get("discarded_by_user")), "dedupe_key": details.get("dedupe_key", ""),
            "source_chats": sources})
    limit = config["max_context_chars"]
    while len(encode(result)) > limit // 2 and (result["existing_items"] or result["current_work"]):
        if result["existing_items"]:
            result["existing_items"].pop()
        elif result["current_work"]:
            result["current_work"].pop()
    prior = db.execute("SELECT * FROM learning_exchanges WHERE session_id=? AND seq<=? ORDER BY seq DESC LIMIT 8",
                       (job["session_id"], job["cursor"])).fetchall()
    for row in prior:
        item = exchange(row)
        item["input_text"], item["output_text"] = item["input_text"][:1500], item["output_text"][:3000]
        if len(encode(result)) + len(encode(item)) > limit * .7:
            break
        result["prior_context"].insert(0, item)
    for row in db.execute("SELECT * FROM learning_exchanges WHERE session_id=? AND seq>? AND seq<=? ORDER BY seq LIMIT 50",
                          (job["session_id"], job["cursor"], job["upto"])):
        item = exchange(row)
        if result["exchanges"] and len(encode(result)) + len(encode(item)) + 2 > limit:
            break
        result["exchanges"].append(item)
        while len(encode(result)) > limit:
            item["input_text"] = item["input_text"][:len(item["input_text"]) // 2]
            item["output_text"] = item["output_text"][:len(item["output_text"]) // 2]
            if not item["input_text"] and not item["output_text"]:
                if result["prior_context"]:
                    result["prior_context"].pop(0)
                elif result["existing_items"]:
                    result["existing_items"].pop()
                else:
                    raise ValueError("Conversation metadata exceeds the context limit")
    return result
