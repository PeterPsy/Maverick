---
name: app-store-ops
description: "Use the Maverick v3 App Store app to inspect the app catalog and install system apps into authorized workspaces through Maverick-owned APIs."
---

# App Store Ops

Use this skill when a user wants to inspect Maverick app catalog entries or install a system app into one or more workspaces.

Rules:

- Read the catalog through the `app.app-store.maverick_app_store` MCP tool or the `app.app-store.app-store` CLI command.
- Install operations must go through Maverick core authenticated APIs, not by copying app source into a workspace.
- App-owned state belongs under `workspaces/<workspace_id>/data/app-store/`.
- The remote public catalog is a source of artifacts. Maverick core owns authentication, authorization, artifact verification, app source registration, and workspace bindings.
