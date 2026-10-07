"""Structural and product relevance gates for generated learning decisions."""

from hashlib import sha256
import json
import re
from urllib.parse import urlparse

from learning_evidence import evidence_for
from learning_review_schema import ITEM_PROPERTIES, POLICY_VERSION

_DEVELOPMENT_REQUEST = re.compile(
    r"(?i)\b(?:voglio|implementa\w*|cambia\w*|modifica\w*|aggiungi\w*|deve avere|ha richiesto|ha stabilito|"
    r"i want|implement|change|add|requested)\b.{0,180}\b(?:toggle|kanban|layout|interfaccia|pulsante|button|ui|frontend)\b")
_UI_REQUIREMENT = re.compile(r"(?i)\b(?:toggle|kanban|layout|pulsante|button|frontend|font size)\b")


def normalize(text):
    return " ".join(re.findall(r"\w+", str(text).casefold()))


def review_output(text, input_data):
    if not isinstance(text, str) or len(text) > 128_000:
        raise ValueError("Analysis output exceeds the allowed size")
    output = json.loads(text)
    if not isinstance(output, dict) or set(output) != {"episode", "memory", "improvements", "reconciliations"}:
        raise ValueError("Invalid analysis output")
    episode = output["episode"]
    if not isinstance(episode, dict) or set(episode) != {"status", "summary", "open_work", "evidence"}:
        raise ValueError("Invalid episode assessment")
    if episode["status"] not in {"completed", "ongoing", "blocked", "uncertain"}:
        raise ValueError("Invalid episode status")
    if not isinstance(episode["summary"], str) or not 1 <= len(episode["summary"].strip()) <= 2000:
        raise ValueError("An episode needs a bounded summary")
    if not isinstance(episode["open_work"], list) or len(episode["open_work"]) > 8 or any(not isinstance(x, str) or not 1 <= len(x) <= 500 for x in episode["open_work"]):
        raise ValueError("Invalid open work")
    evidence = evidence_for(episode["evidence"], input_data, completed=episode["status"] == "completed")
    if episode["status"] == "completed":
        new_turns = {x["turn_id"] for x in input_data["exchanges"]}
        if episode["open_work"] or not any(x["turn_id"] in new_turns for x in evidence):
            raise ValueError("A completed episode requires a new outcome and no remaining work")
    episode = {**episode, "evidence": evidence}
    items = []
    for field, kind in (("memory", "memory"), ("improvements", "improvement")):
        raw_items = output[field]
        if not isinstance(raw_items, list) or len(raw_items) > 3:
            raise ValueError("Too many analysis items")
        if not input_data.get(field + "_enabled", True):
            continue
        for raw in raw_items:
            item = validate_candidate(raw, kind, input_data)
            if episode["status"] == "completed" and eligible(item):
                item["policy_version"] = POLICY_VERSION
                item["reviewed_sources"] = input_data.get("source_revisions", {})
                items.append(item)
    reconciliations = validate_reconciliations(output["reconciliations"], input_data)
    return {"episode": episode, "items": items, "reconciliations": reconciliations}


def validated_items(text, input_data):
    return review_output(text, input_data)["items"]


def validate_candidate(raw, kind, input_data):
    if not isinstance(raw, dict) or set(raw) != set(ITEM_PROPERTIES):
        raise ValueError("Invalid candidate fields")
    item = dict(raw)
    for key in ("title", "body", "dedupe_key"):
        if not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > (4000 if key == "body" else 240):
            raise ValueError("Invalid candidate text")
    if not normalize(item["dedupe_key"]) or not normalize(item["body"]):
        raise ValueError("Candidate text must contain words")
    for key, schema in ITEM_PROPERTIES.items():
        if "enum" in schema and item[key] not in schema["enum"]:
            raise ValueError("Invalid candidate classification")
    if not isinstance(item["explicit"], bool) or not isinstance(item["durable"], bool):
        raise ValueError("Invalid evidence flags")
    for key in ("category", "expected_impact", "effort", "verification", "generalization"):
        if not isinstance(item[key], str) or len(item[key]) > 1000:
            raise ValueError("Invalid proposal details")
    confidence = item["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("Invalid confidence")
    item["evidence"] = evidence_for(item["evidence"], input_data, completed=kind == "memory")
    refs = item["source_refs"]
    if not isinstance(refs, list) or len(refs) > 8 or any(not isinstance(x, str) or not 1 <= len(x) <= 1000 for x in refs):
        raise ValueError("Invalid knowledge sources")
    turns = {x["turn_id"]: x for x in input_data.get("prior_context", []) + input_data["exchanges"]}
    sources = "\n".join(turns[x["turn_id"]]["input_text" if x["role"] == "user" else "output_text"] for x in item["evidence"])
    if any(ref not in sources or not valid_source_ref(ref) for ref in refs):
        raise ValueError("Knowledge source is absent from the cited exchange")
    item["kind"] = kind
    identity = normalize(item["body"] if kind == "memory" else item["dedupe_key"])
    item["fingerprint"] = sha256((kind + ":" + identity).encode()).hexdigest()
    return item


def eligible(item):
    if item["novelty"] != "new":
        return False
    if item["kind"] == "improvement":
        return (item["scope"] == "maverick" and item["problem_kind"] != "none"
                and bool(item["generalization"].strip()) and bool(item["verification"].strip()))
    if item["scope"] != "knowledge" or not item["durable"] or item["memory_type"] in {"none", "development"} or item["confirmation"] != "confirmed":
        return False
    if any(_DEVELOPMENT_REQUEST.search(text) for text in [item["body"], *[x["quote"] for x in item["evidence"]]]):
        return False
    if item["memory_type"] in {"preference", "decision"} and _UI_REQUIREMENT.search(item["title"] + " " + item["body"]):
        return False
    if any(x["role"] == "assistant" for x in item["evidence"]) and not item["source_refs"]:
        return False
    return True


def valid_source_ref(ref):
    if ref.startswith("app_ref:"):
        return bool(re.fullmatch(r"app_ref:[\w-]+/[\w-]+/[\w:.-]+", ref))
    parsed = urlparse(ref)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not parsed.username and not parsed.password


def validate_reconciliations(raw, input_data):
    if not isinstance(raw, list) or len(raw) > 20:
        raise ValueError("Invalid reconciliation list")
    ids = {x["id"] for x in input_data.get("existing_items", [])}
    result = []
    seen = set()
    for row in raw:
        if not isinstance(row, dict) or set(row) != {"item_id", "disposition", "reason", "evidence"}:
            raise ValueError("Invalid reconciliation")
        if row["item_id"] not in ids or row["item_id"] in seen or row["disposition"] not in {"keep", "in_progress", "resolved", "duplicate", "irrelevant"}:
            raise ValueError("Unknown or repeated reconciliation target")
        if not isinstance(row["reason"], str) or not 1 <= len(row["reason"].strip()) <= 1000:
            raise ValueError("Invalid reconciliation reason")
        seen.add(row["item_id"])
        result.append({**row, "evidence": evidence_for(row["evidence"], input_data)})
    return result
