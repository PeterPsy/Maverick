# Videomaker Selection

Workspace-local Maverick app for cataloguing and managing Social Video Editor candidates.

## Included surfaces

- Full responsive React workspace with ranking, filters, bulk decisions, profile drawer, notes and JSON/CSV export.
- Separate portfolio, Instagram-profile and test-video sections, with automatic recovery of multiple URLs from free-form form responses.
- `base-shell` primary sidebar widget with live aggregate buttons that filter the workspace catalog.
- `base-shell` footer widget for creating a candidate, including the shell primary-action protocol.
- Persistent SQLite backend with candidate CRUD, activity timeline, pipeline statistics and deterministic import/export.
- Official CLI, MCP, reference entity and view-state surfaces.
- Idempotent install, migration and health hooks.

## Data ownership

All mutable app state is stored only in the app-owned data root:

```text
data/videomaker-selection/app.db
```

The app has no outbound network permission, no secret access, no dependency on another app and no uninstall/purge hook. App-source removal and any later uninstall can therefore be handled separately without touching unrelated workspace data.

## Pipeline

- Decision: `da_valutare`, `scartato`, `riserva`, `selezionato`
- Email: `da_contattare`, `email_inviata`, `risposta_ricevuta`, `nessuna_risposta`
- Call: `non_prevista`, `da_fissare`, `fissata`, `fatta`, `no_show`
- POC: `non_previsto`, `da_proporre`, `proposto`, `in_corso`, `completato`

## Development checks

```bash
npm run build
PYTHONPATH=/home/ubuntu/projects/maverick-v3 python3 -m unittest discover -s tests -v
maverick core cli run core.app-sdk.validate --app-id videomaker-selection --workspace default --json
maverick core cli run core.app-sdk.status --app-id videomaker-selection --workspace default --json
```
