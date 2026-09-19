"""Preserve source relationships as validated CRM IDs, never guessed provider IDs."""

def extract_links(table, row, source_key, item):
    from .versy_adapter import array
    links = []
    foreign = {}
    direct = {
        "interactions": {"contact_id": "contacts"}, "follow_ups": {"contact_id": "contacts"},
        "outreach_campaign_variants": {"campaign_id": "outreach_campaigns"},
        "outreach_campaign_steps": {"campaign_id": "outreach_campaigns"},
        "outreach_campaign_enrollments": {"campaign_id": "outreach_campaigns", "variant_id": "outreach_campaign_variants"},
        "outreach_campaign_events": {"campaign_id": "outreach_campaigns"},
    }
    for field, target_table in direct.get(table, {}).items():
        if row.get(field):
            foreign[field] = f"{target_table}:{row[field]}"
    if table in {"property_listings", "presentation_generations"}:
        foreign["definition_id"] = f"definition:{table}"
    if table == "outreach_campaign_enrollments":
        foreign["record_id"] = f"real_estate_agencies:{row.get('agency_id', '')}"
    if table == "outreach_campaign_events" and row.get("enrollment_id"):
        foreign["member_id"] = f"outreach_campaign_enrollments:{row['enrollment_id']}"
    item["foreign"] = foreign
    array_fields = {"participant_ids": ("contacts", "participant"), "contact_ids": ("contacts", "related"),
                    "task_ids": ("follow_ups", "follow_up"), "thread_ids": ("conversation_threads", "conversation")}
    for field, (target_table, relation) in array_fields.items():
        for target_id in array(row.get(field)):
            links.append({"source_key": source_key, "target_key": f"{target_table}:{target_id}", "relationship": relation})
    for field, target_table in {"primary_contact_id": "contacts", "contact_id": "contacts",
                                "agency_id": "real_estate_agencies", "listing_id": "property_listings",
                                "property_listing_id": "property_listings"}.items():
        if row.get(field) and field not in foreign:
            links.append({"source_key": source_key, "target_key": f"{target_table}:{row[field]}", "relationship": "related"})
    # thread_id can be an external Gmail thread ID, not a CRM conversation ID.
    # Keep it in provenance until provider identity reconciliation, never invent a link.
    return links
