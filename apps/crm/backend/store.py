"""Public persistence facade for CRM."""

from database import ensure_schema, health_payload
from records import add_activity, create_account, create_contact, create_deal, inspect_entity, link_entities
from retrieval import REFERENCE_MANIFEST, list_deals, list_recent, reference_resolve, reference_search, reference_summarize, search_records

__all__ = [
    "REFERENCE_MANIFEST",
    "add_activity",
    "create_account",
    "create_contact",
    "create_deal",
    "ensure_schema",
    "health_payload",
    "inspect_entity",
    "link_entities",
    "list_deals",
    "list_recent",
    "reference_resolve",
    "reference_search",
    "reference_summarize",
    "search_records",
]
