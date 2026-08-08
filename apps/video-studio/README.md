# Video Studio

Video Studio is Maverick's installation-level, server-first video editor. This
checkpoint establishes its production storage and hosting foundation; project
editing, media analysis, rendering, and agent proposal capabilities are added
by later contract-first slices and are intentionally not advertised yet.

## Ownership and installation states

The source artifact is `apps/video-studio/`. It is `source_available` and
`forkable`, but it is not a workspace-local project. Source presence alone does
not make the app usable:

1. Maverick generically parses `app_contract.json` and registers the source as
   an installation-level `platform` source.
2. Generic app hosting installs that source into a workspace and creates an
   enabled workspace binding.
3. The binding owns data at
   `workspaces/<workspace_id>/data/video-studio/` and keeps source outside the
   workspace.

The normal built-in bootstrap or the generic
`register_app_source_from_contract(...)` plus `install_store_app(...)` flow owns
registration and binding. Video Studio has no app-specific installer and does
not use workspace-local app registration.

## Implemented surfaces

- mounted frontend artifact and source build;
- mounted backend actions `status`, `schema`, `health`, and `capabilities`;
- CLI command `video-studio` with the same actions;
- MCP tool `video_studio_foundation` with the same actions and the required
  empty `video_studio_reference_manifest` until reference entities are real;
- idempotent `install`, `migrate`, and `health_check` hooks;
- bundled `video-studio-ops` skill;
- a governed read-only HTTP sidecar exposing exact GET routes for foundation
  status, schema, and health.

The sidecar is sandbox-required, uses a read-only app bundle, has no inherited
host environment or outbound network, receives a per-process technical token,
and writes only to the binding's app data root. Its platform proxy is
deny-by-default outside the three declared routes.

## Storage foundation

The canonical store is `data/video-studio/app.db`, an app-owned SQLite database
at schema version 1. Migrations are ordered, checksummed, contiguous, and
transactional. Connections enforce foreign keys and prefer WAL, with a checked
rollback-journal fallback for hosts where WAL is unavailable.

Schema v1 contains 23 domain aggregates for projects and revisions, media and
analysis, edit proposals, renders, templates, recipes, and audit events, plus
`app_metadata` and `schema_migrations`. JSON columns are validated, foreign-key
relationships are explicit, and query paths used by future slices are indexed.

The hook also prepares only these app-owned directories:

```text
data/video-studio/
  app.db
  migrations/
  project-snapshots/
  indices/{text,vector}/
  cache/{probes,proxies,thumbnails,waveforms,frames,model-results,remotion-bundles}/
  jobs/{logs,staging}/
  models/manifests/
  audit/
  tmp/
```

Media bytes and final outputs remain Storage-owned. The contract requires
typed `file.*` provider interfaces by alias; app code must not read another
app's database or hardcode a provider app id.

## Validation

From the Maverick repository root, validate the installation-level source with
the canonical SDK validator by supplying its source path:

```bash
maverick core cli run core.app-sdk.validate --app-root apps/video-studio --json
```

Run the focused engineering checks with:

```bash
python3 -m unittest discover -s apps/video-studio/tests -p 'test_*.py'
python3 -m compileall apps/video-studio/backend apps/video-studio/cli apps/video-studio/mcp apps/video-studio/hooks apps/video-studio/tests
python3 scripts/check_unused_imports.py
```

Tests separately verify contract/source validity, registration as an
installation-level source, creation of an enabled workspace binding, lifecycle
idempotency, path confinement, migration rollback/checksums, and parity across
backend, CLI, MCP, and sidecar foundation responses.
