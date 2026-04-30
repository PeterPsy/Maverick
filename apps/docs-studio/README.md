# Docs Studio

Docs Studio is a workspace-local app for creating polished, GitBook-style documentation experiences. It owns its app source under `apps/docs-studio` and composes documentation from file-backed and runtime sources.

## Product Surface

- Frontend: a three-pane documentation workspace with navigation, page preview, editing controls, and an assistant panel.
- Frontend source: React/Vite under `frontend/src`, built into `frontend/dist` through the Maverick frontend lifecycle.
- Backend: JSON actions for status, state loading, site updates, workspace page creation, and workspace page updates.
- CLI/MCP: targeted documentation manifest, search, page read, status, state, and reference surfaces for workspace agents.
- Storage: lightweight configuration under `data/docs-studio/state.json`; workspace-authored Markdown pages under `data/docs-studio/pages/`.

## Contract Notes

- Frontend, backend, CLI, MCP, storage, references, view state, and data events are declared in `app_contract.json`.
- Docs Studio owns workspace documentation state under `data/docs-studio/`.
- Operational permissions are declared explicitly; the app does not request secrets, host telemetry, or runtime cleanup.

## Documentation Sources

Docs Studio is a runtime documentation composer:

- Curated docs live as Markdown source files under `docs/pages/`, with ordering and page metadata in `docs/manifest.json`.
- Workspace-created docs live under `data/docs-studio/pages/` with a small workspace manifest.
- App documentation is read live from app `README.md` files and `app_contract.json` files in workspace and server app sources.
- Contract overview sections are derived from the current app contract at request time and are not persisted as documentation text.
- `data/docs-studio/state.json` stores only site configuration and view state.

## Agent Query Surfaces

Agents should use Docs Studio's app-scoped surfaces when they need Maverick documentation context. These calls return the relevant documentation slice instead of pulling broad core developer context.

```bash
maverick app docs-studio cli run docs-studio --subcommand manifest --section_id core-architecture
maverick app docs-studio cli run docs-studio --subcommand search --query "provider credentials" --limit 5
maverick app docs-studio cli run docs-studio --subcommand read --page_id provider-credentials --max_chars 12000
```

Equivalent MCP tools:

- `docs_studio_docs_manifest`: compact table of contents, optionally filtered by `section_id`.
- `docs_studio_docs_search`: ranked search with optional `section_id`, `source_app_id`, `limit`, and `max_chars`.
- `docs_studio_docs_read`: Markdown body for one page by `page_id`, with optional `max_chars`.

The full `docs_studio_state` surface remains available for the UI and diagnostics, but agent workflows should prefer the targeted tools above.

## Design DNA

The source visual reference is decomposed in `DESIGN_DNA.md`. In short: use a dense documentation shell, soft off-white canvas, warm gray text, black headings, a restrained coral accent, 1px dividers, compact icon rows, preview cards, and a fixed assistant rail on the right.

## SDK Flow

```bash
maverick core cli run core.app-sdk.validate --app-id docs-studio --workspace default --json
maverick core cli run core.app-sdk.register-local --app-id docs-studio --workspace default --json
maverick core cli run core.app-sdk.install-local --app-id docs-studio --workspace default --json
maverick core cli run core.app-sdk.status --app-id docs-studio --workspace default --json
maverick core cli run core.app-sdk.package --app-id docs-studio --workspace default --json
```

## Rebuild Frontend

```bash
maverick app docs-studio frontend build --json
```
