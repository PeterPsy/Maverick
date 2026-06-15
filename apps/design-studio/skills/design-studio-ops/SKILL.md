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

Sandbox policy:

- Do not use host absolute paths as design sources.
- Do not request `/api/import/folder`, terminal, or pty routes in sandbox mode.
- Provider credentials must remain in Maverick/Vault-owned flows; do not persist provider keys in OpenDesign media config.

The initial app ships with a governed OpenDesign-compatible sidecar stub pinned to upstream OpenDesign `0.10.1` metadata. Replacing it with the real daemon must keep the same route policy and Storage/Vault boundaries.
