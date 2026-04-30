---
name: app-store-ops
description: "Use the Maverick App Store app to inspect catalogs, install apps, and submit app source to the external public App Store."
---

# App Store Ops

Use this skill when a user wants to inspect Maverick app catalog entries, install a system app into one or more workspaces, or submit an app to the external public App Store.

Rules:

- Read the catalog through the `app.app-store.maverick_app_store` MCP tool or the `app.app-store.app-store` CLI command.
- Install operations must go through Maverick core authenticated APIs, not by copying app source into a workspace.
- App-owned state belongs under `workspaces/<workspace_id>/data/app-store/`.
- The remote public catalog is a source of artifacts. Maverick core owns authentication, authorization, artifact verification, app source registration, and workspace bindings.
- Public publication approval is not a Maverick core workflow. Maverick `apps/app-store` is only a submission/status client for the external public store service.
- Public publication requests generated from the App Store UI package the selected workspace-local app into a `.zip` automatically; users should not be asked to upload the ZIP manually in that flow.
- Public identity is stored in app contract metadata as `public_store.public_app_uuid`. Generate and save it before the first public submission when absent, then reuse it for future updates; users should not type or edit it.
- Public publication requests must choose a packaging mode: `sealed` for a non-editable build artifact, or `forkable` for source-available publication. Send this as `publication_mode`.
- The external public store owns review, approval, rejection, retry, and catalog publication, and keys public catalog publication by `public_app_uuid` rather than by app name or `app_id`.
- Keep internal server promotion distinct from public publication: "Promote to server app" updates the local Maverick installation; "Request public publication" submits to the external public store.
