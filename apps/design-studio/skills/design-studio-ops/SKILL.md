---
name: design-studio-ops
description: Use the Design Studio app to inspect design projects, import Storage files, export design artifacts, and verify the governed OpenDesign sidecar.
---

# Design Studio Ops

Use Design Studio through its official Maverick app surfaces.

Common operations:

- Inspect app state with MCP tool `design_studio_state` or CLI command `design-studio --action state`.
- Create a design project through the mounted frontend or backend action `create_project`.
- Import only workspace Storage files using `workspace_relative_path` values under `storage/uploaded/` or `storage/generated/`; hosted imports are read through the `storage-read` dependency backend.
- Export project metadata and notes to `storage/generated/design-studio/<project-id>/` through the `storage-write` dependency backend.
- Verify the OpenDesign sidecar through the app state `sidecar.ready_url` or `sidecar.version_url`.
- Resolve an OpenDesign project id with MCP tool `design_studio_get_project` or
  CLI action `get_project`; these entrypoints use the short-lived core
  `app_sidecar` broker and never read OpenDesign SQLite/files directly.
- Search, resolve, or summarize `design_project` references through the
  declared Design Studio reference tools. Reference capability routes are
  GET-only and cannot be used to mutate OpenDesign.
- Use `POST /api/provider/models` only through the mounted Design Studio sidecar route when checking OpenDesign model discovery; it is handled by Maverick core/app code and must report `sidecar_reached: false`.
- Treat `service/opendesign_launcher.py` as the sidecar entrypoint. It resolves
  only the bundle digest and data generation named together by the validated
  `control.json`; it never builds, migrates, or selects a "latest" directory.
- Treat the pinned `ghcr.io/nexu-io/od:0.16.1` OCI image as the primary
  distribution. `service/import_opendesign_oci.py` performs two verified
  derivations without Docker or a local Next build; the launcher uses only the
  materialized image loader and Node runtime.

Sandbox policy:

- Do not use host absolute paths as design sources.
- Do not request `/api/import/folder`, terminal, or pty routes in sandbox mode.
- Provider credentials must remain in Maverick/Vault-owned flows. Do not put provider keys in browser payloads, sidecar requests, backend app secrets, or OpenDesign media config.
- Design Studio declares provider model proxy access only; it must not receive raw provider keys and must not expose provider generation/chat routes directly to OpenDesign.
- Do not guess a sidecar port, reuse a broker descriptor after the entrypoint
  ends, or fall back to `data/design-studio/opendesign/app.sqlite`. Capability
  expiry or denial is a hard failure.
- Use `bootstrap_opendesign_generation.py` only for a new empty data root. It
  refuses legacy or unknown content. Existing data migration requires an
  explicitly marked fixture/controlled copy and is never implied by startup.
- `smoke_opendesign_migration.py` is the authorized real-daemon migration and
  rollback proof because it creates temporary marked copies. It is not an
  authorization to migrate the current workspace data root.
- Keep full source-build certification separate from OCI import. Do not resume a
  per-file checkpoint or create shards/retries when the host lacks capacity.

The exact upstream release, commit, patch set, artifact digest, and file
manifest come only from `service/opendesign_bundle.json`. Materialized bundles
live in immutable `service/vendor/open-design/<artifact-sha256>/` directories.
The declared runtime fails closed without a verified bundle and matching active
data generation; there is no compatibility fallback.

Release verification uses `service/smoke_opendesign_runtime.py` for the real
imported daemon and `service/smoke_opendesign_sidecar.py` for launcher/core
proxy behavior. The redaction-safe evidence record is
`service/opendesign_oci_acceptance_0_16_1.json`.
