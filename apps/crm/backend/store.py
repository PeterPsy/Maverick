"""Public persistence facade for CRM."""

from database import ensure_schema, health_payload
from records import add_activity, create_account, create_contact, create_deal, inspect_entity, link_entities
from retrieval import REFERENCE_MANIFEST, list_deals, list_recent, reference_resolve, reference_search, reference_summarize, search_records
from view_state import clear_custom_view_payload, load_view_state, set_custom_view_payload, set_view_filter_payload

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
    "load_view_state",
    "reference_resolve",
    "reference_search",
    "reference_summarize",
    "search_records",
    "clear_custom_view_payload",
    "set_custom_view_payload",
    "set_view_filter_payload",
]
