"""Memory app constants and schema metadata."""

SCHEMA_VERSION = "2"
APP_ID = "memory"

NODE_TYPES = {
    "note",
    "fact",
    "file_ref",
    "app_entity_ref",
    "person_ref",
    "company_ref",
    "project_ref",
    "topic",
    "decision",
    "question",
}

EDGE_KINDS = {
    "related_to",
    "supports",
    "contradicts",
    "mentions",
    "derived_from",
    "about",
    "owned_by",
    "requested_by",
    "depends_on",
    "same_as",
    "supersedes",
}
