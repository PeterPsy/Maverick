"""Build bounded new evidence and a small amount of prior context."""

import json


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def build_input(db, job, config, *, memory_provider_app_id=""):
    result = {"session_id": job["session_id"], "exchanges": [], "prior_context": [],
              "memory_enabled": config["memory_enabled"], "improvements_enabled": config["improvements_enabled"],
              "memory_provider_app_id": memory_provider_app_id}
    prior = db.execute("SELECT input_text,output_text FROM learning_exchanges WHERE session_id=? AND seq<=? ORDER BY seq DESC LIMIT 2",
                       (job["session_id"], job["cursor"])).fetchall()
    for row in reversed(prior):
        result["prior_context"].append({"input_text": row[0][:500], "output_text": row[1][:500]})
    for row in db.execute("SELECT * FROM learning_exchanges WHERE session_id=? AND seq>? AND seq<=? ORDER BY seq LIMIT 50",
                          (job["session_id"], job["cursor"], job["upto"])):
        item = dict(row)
        item["metrics"] = json.loads(item["metrics"])
        if result["exchanges"] and len(encode(result)) + len(encode(item)) + 2 > config["max_context_chars"]:
            break
        result["exchanges"].append(item)
        while len(encode(result)) > config["max_context_chars"]:
            item["input_text"] = item["input_text"][:len(item["input_text"]) // 2]
            item["output_text"] = item["output_text"][:len(item["output_text"]) // 2]
            if not item["input_text"] and not item["output_text"]:
                raise ValueError("Conversation metadata exceeds the context limit")
    return result
