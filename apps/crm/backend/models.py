"""CRM domain constants."""

SCHEMA_VERSION = "1"

ENTITY_TYPES = {"account", "contact", "deal", "activity"}

RELATIONSHIP_KINDS = {
    "related_to",
    "works_at",
    "owns",
    "influences",
    "mentions",
    "requested_by",
    "depends_on",
    "competitor_for",
}

ACTIVITY_TYPES = {"call", "email", "meeting", "note", "task", "other"}
