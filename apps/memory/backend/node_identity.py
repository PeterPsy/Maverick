"""Content identity independent of persistence and caller confidence."""

from hashlib import sha256
import json


def identity_key(node: dict) -> str:
    metadata = node.get("metadata") or {}
    scope = {key: metadata.get(key) for key in ("person_id", "project_id", "knowledge_type", "valid_from", "valid_until")}
    content = [node.get("type"), *[" ".join(str(node.get(key) or "").split()).casefold()
                                for key in ("title", "summary", "body_text")], scope]
    return sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
