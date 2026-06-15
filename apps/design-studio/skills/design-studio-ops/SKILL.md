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
- Treat `service/opendesign_launcher.py` as the sidecar entrypoint. It starts a curated OpenDesign bundle from `service/vendor/open-design/` when that bundle has been materialized.

Sandbox policy:

- Do not use host absolute paths as design sources.
- Do not request `/api/import/folder`, terminal, or pty routes in sandbox mode.
- Provider credentials must remain in Maverick/Vault-owned flows; do not persist provider keys in OpenDesign media config.

The app uses a governed OpenDesign launcher pinned to upstream OpenDesign `0.10.1` metadata. `service/opendesign_compat.py` is only a manual diagnostics/test fallback when `MAVERICK_OPENDESIGN_ALLOW_FALLBACK=1`; the declared runtime fails closed without a materialized curated bundle.
