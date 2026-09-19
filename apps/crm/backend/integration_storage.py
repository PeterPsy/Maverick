"""Durable provider operation journal; business ownership remains with providers."""

def initialize_integrations(db):
    db.execute("""CREATE TABLE IF NOT EXISTS integration_operations (
        id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
        kind TEXT NOT NULL, provider_alias TEXT NOT NULL, provider_app_id TEXT NOT NULL,
        request_json TEXT NOT NULL, status TEXT NOT NULL, proposal_id TEXT NOT NULL DEFAULT '',
        attempt_id TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
        result_json TEXT NOT NULL DEFAULT '{}', last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_integration_record ON integration_operations(entity_type, entity_id, updated_at)")
