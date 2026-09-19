"""Closed CRM entity catalog shared by storage, discovery and validation."""

BASE_ENTITIES = {
    "lead": "leads", "account": "accounts", "contact": "contacts", "deal": "deals",
    "activity": "activities", "task": "tasks", "note": "notes",
}

# Each extension has a title, body, owner, metadata and the standard lifecycle.
# Field kinds are deliberately closed; callers cannot submit SQL/schema fragments.
EXTENSIONS = {
    "conversation_thread": {"table": "conversation_threads", "fields": {
        "channel": "text", "status": "text", "last_activity_at": "date",
    }, "defaults": {"status": "open", "channel": "manual"}},
    "campaign": {"table": "campaigns", "fields": {
        "channel": "text", "status": "text", "objective": "text", "segment": "json",
    }, "defaults": {"status": "draft", "channel": "email"}},
    "campaign_variant": {"table": "campaign_variants", "fields": {
        "campaign_id": "ref:campaign", "subject": "text", "weight": "integer",
    }, "required": ["campaign_id"], "defaults": {"weight": 100}},
    "campaign_step": {"table": "campaign_steps", "fields": {
        "campaign_id": "ref:campaign", "variant_id": "ref:campaign_variant",
        "position": "integer", "delay_hours": "integer", "channel": "text",
    }, "required": ["campaign_id"]},
    "campaign_member": {"table": "campaign_members", "fields": {
        "campaign_id": "ref:campaign", "variant_id": "ref:campaign_variant",
        "record_type": "text", "record_id": "text", "status": "text", "next_action_at": "date",
    }, "required": ["campaign_id", "record_type", "record_id"], "defaults": {"status": "pending"}},
    "campaign_event": {"table": "campaign_events", "fields": {
        "campaign_id": "ref:campaign", "member_id": "ref:campaign_member",
        "event_type": "text", "occurred_at": "date",
    }, "required": ["campaign_id"], "defaults": {"event_type": "note"}},
    "expense": {"table": "expenses", "fields": {
        "amount_minor": "integer", "currency": "text", "incurred_at": "date",
        "category": "text", "supplier": "text", "deal_id": "ref:deal", "account_id": "ref:account",
    }, "defaults": {"currency": "EUR"}},
    "brief": {"table": "briefs", "fields": {
        "period_start": "date", "period_end": "date", "status": "text",
    }, "defaults": {"status": "draft"}},
    "intelligence_profile": {"table": "intelligence_profiles", "fields": {
        "category": "text", "website": "text", "reviewed_at": "date",
    }, "defaults": {"category": "competitor"}},
    "custom_object_definition": {"table": "custom_object_definitions", "fields": {
        "object_key": "text", "fields": "json",
    }, "required": ["object_key"]},
    "custom_object_record": {"table": "custom_object_records", "fields": {
        "definition_id": "ref:custom_object_definition", "fields": "json",
    }, "required": ["definition_id"]},
}

ENTITY_TABLES = {**BASE_ENTITIES, **{entity: spec["table"] for entity, spec in EXTENSIONS.items()}}
TABLE_ENTITIES = {table: entity for entity, table in ENTITY_TABLES.items()}
