"""Interface-selected provider references; no credentials or implicit side effects."""

from errors import ValidationError
from store import require_text
from .external_refs import link_external_ref

PROVIDERS = {
    "mail": "mail.workspace", "calendar": "calendar.events", "files": "file.catalog",
    "file-preview": "file.preview", "file-write": "file.content.write",
    "speech": "speech.transcription", "tasks": "checklist.task",
}


def integration_context(db, payload):
    raw = payload.get("_app_dependencies", {})
    dependencies = raw.get("dependencies", []) if isinstance(raw, dict) else []
    selected = {}
    for dependency in dependencies if isinstance(dependencies, list) else []:
        if isinstance(dependency, dict):
            ids = dependency.get("selected_provider_app_ids", [])
            if isinstance(ids, list):
                selected[dependency.get("alias")] = [item for item in ids if isinstance(item, str) and item]
    return {"ok": True, "providers": [
        {"alias": alias, "interface": interface, "selected_provider_app_ids": selected.get(alias, []),
         "configured": len(selected.get(alias, [])) == 1,
         "linked_count": db.execute("SELECT count(*) FROM external_refs WHERE provider_alias=? AND deleted_at IS NULL", (alias,)).fetchone()[0]}
        for alias, interface in PROVIDERS.items()], "delivery_supported": False}


def link_provider_record(db, payload):
    alias = require_text(payload, "provider_alias", required=True)
    providers = {provider["alias"]: provider for provider in integration_context(db, payload)["providers"]}
    provider = providers.get(alias)
    if not provider or not provider["configured"]:
        raise ValidationError("Select exactly one enabled provider for this interface in workspace Settings first.")
    # The actor supplies a record identity obtained from the selected provider.
    # It is still an unresolved snapshot, not evidence of a successful remote read.
    fields = {key: payload[key] for key in ("crm_entity_type", "crm_entity_id", "source_entity_type", "source_entity_id", "link_type", "title", "summary", "occurred_at") if key in payload}
    fields.update(source_app_id=provider["selected_provider_app_ids"][0], provider_alias=alias,
                  source_interface=provider["interface"], metadata={"resolution_status": "unresolved"})
    return {"ok": True, "external_ref": link_external_ref(db, fields)}
