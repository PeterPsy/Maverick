"""Exact bounded provenance shared by episode and candidate validation."""


def evidence_for(raw, input_data, *, completed=False, allow_empty=False):
    if not isinstance(raw, list) or len(raw) > 5 or (not raw and not allow_empty):
        raise ValueError("Each decision requires bounded evidence")
    turns = {x["turn_id"]: x for x in input_data.get("prior_context", []) + input_data["exchanges"]}
    result = []
    for cited in raw:
        if not isinstance(cited, dict) or set(cited) != {"turn_id", "role", "quote"}:
            raise ValueError("Invalid evidence")
        turn_id, role, quote = cited["turn_id"], cited["role"], cited["quote"]
        if not isinstance(turn_id, str) or role not in {"user", "assistant"} or not isinstance(quote, str) or not 8 <= len(quote.strip()) <= 2000:
            raise ValueError("Invalid evidence")
        turn = turns.get(turn_id)
        if not turn or quote not in turn["input_text" if role == "user" else "output_text"]:
            raise ValueError("Evidence quote does not match the source")
        if completed and turn["status"] != "completed":
            raise ValueError("Confirmed knowledge requires completed evidence")
        result.append({**cited, "session_id": input_data["session_id"], "metrics": turn.get("metrics", {})})
    return result
