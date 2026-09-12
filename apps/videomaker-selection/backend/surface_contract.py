"""Compact discovery contract for agent and CLI callers."""

OPERATIONS = [
    {"action": "status", "effect": "read", "description": "Database and catalog status."},
    {"action": "list", "effect": "read", "description": "Filter and sort candidates."},
    {"action": "stats", "effect": "read", "description": "Pipeline aggregate counts."},
    {"action": "read", "effect": "read", "description": "Read a candidate and activity timeline."},
    {"action": "create", "effect": "mutating", "description": "Create a candidate."},
    {"action": "update", "effect": "mutating", "description": "Update candidate profile or pipeline."},
    {"action": "bulk_update", "effect": "mutating", "description": "Update up to 200 candidates."},
    {"action": "activity.add", "effect": "mutating", "description": "Append a timeline note."},
    {"action": "import", "effect": "mutating", "description": "Upsert normalized candidate objects."},
    {"action": "export", "effect": "read", "description": "Export full app-owned catalog state."},
    {"action": "delete", "effect": "destructive", "description": "Delete one candidate after confirmation."},
]


def operations_manifest() -> dict:
    return {
        "app_id": "videomaker-selection", "schema_version": "1", "operations": OPERATIONS,
        "pipeline": {
            "decision": ["da_valutare", "scartato", "riserva", "selezionato"],
            "email_status": ["da_contattare", "email_inviata", "risposta_ricevuta", "nessuna_risposta"],
            "call_status": ["non_prevista", "da_fissare", "fissata", "fatta", "no_show"],
            "poc_status": ["non_previsto", "da_proporre", "proposto", "in_corso", "completato"],
        },
    }
