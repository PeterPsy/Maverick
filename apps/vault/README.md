# Vault

Vault is the workspace-facing Active Credentials and Connection Issues app for Core Secrets.

It does not own secret values. Secret values remain platform-owned control-plane records under the `core.secrets` domain. Vault calls core HTTP APIs to inspect redaction-safe inventory, grants, and audit metadata from its main frontend. Normal sidebar workflows cover credential add, credential rotation, issue review, and CSV import through controlled core endpoints; grant mechanics remain an advanced/admin diagnostic surface rather than a normal user workflow.

## Surfaces

- Frontend: `frontend/dist`
- Widgets:
  - `vault-sidebar` for `base-shell` content kind `shell.sidebar.primary`
  - `vault-sidebar-footer` for `base-shell` content kind `shell.sidebar.footer`
- Backend: none
- CLI: `vault`, redaction-safe agent operations that diagnose Core Secrets connection issues, plan/explain fixes, and delegate guarded grant creation to core-owned secret surfaces
- MCP: `maverick_vault`, the same redaction-safe agent operations over MCP
- Skills: bundled `vault-ops` guidance for Core Secrets administration

## Storage

Vault does not persist app-owned workspace data. It must not write secret values under `workspaces/<workspace_id>/data/vault/`. Maverick may still create the generic `.maverick-app.json` marker in that directory for app installation metadata; that marker is not a Vault data store.

## Permissions

Vault declares no app secret read/write permissions. It uses authenticated admin core APIs, and those APIs never return raw secret values.

## SDK Flow

Vault is a built-in sealed platform app under `apps/vault`, not a workspace-local SDK project. The source is maintained in the repository, the contract is parsed by the generic app-hosting bootstrap, and the app is installed into workspaces through the same built-in app registration flow as other first-party apps.

## Validation

Validate the app contract with the core app contract parser or by running the focused built-in app tests. Rebuild the frontend with:

```bash
cd apps/vault
npm ci
npm run build
```

## Contract Notes

- Distribution is `sealed` with `source_access: none`.
- Runtime compatibility is sandbox-only because Vault is a frontend surface over authenticated core APIs; it does not need full-access execution.
- Storage is `none`; Core Secrets owns encrypted values, grants, revocation state, and audit.
- The main frontend has two normal user screens: Active Credentials and Connection Issues. Normal users see active credential metadata, app usage, health, issue count, last update time, and redaction-safe connection issues. It does not create, import, rotate, disable, revoke, or grant secrets from the main view.
- Connection Issues consume the redaction-safe Core Secrets recommendation/need payload when available, including human labels, credential match state, recommended grant specs, and user action. The temporary frontend fallback still uses secret inventory, grant inventory, app grant target consumers, resource-scoped selector metadata, and runtime provider status, but the normal UX is issue-oriented rather than grant-console-oriented.
- Grant creation uses Core Secrets validation for active secrets, enabled and mountable workspace apps, target app `permissions.secrets.read` declarations for `app.backend` logical names, non-overlapping active target coverage for each logical name and optional `resource_type`/`resource_id` scope, optional expiry, and app delivery targets that match declared backend or descriptor `required_secrets` consumers. Vault can review this state in Advanced/Admin diagnostics, but the normal sidebar no longer composes grant targets, logical names, CLI/MCP selectors, custom targets, or resource scopes.
- Sidebar widgets keep only the guided credential and import controls: credential creation, credential detail editing, credential rotation, connection issue actions, and CSV import. Save credential asks only for a required title and key by default; alias, type, and description stay collapsed under Optional for users who know them. Existing credentials can be selected in the sidebar to edit redaction-safe metadata, view an obscured current key placeholder, and optionally paste a new key to rotate the value through Core Secrets. Add, edit, and rotate forms send raw values directly to controlled Core Secrets HTTP endpoints and reset secret value fields after submit; raw values are never displayed after submission. CSV import enforces a file-size limit, row-count limit, row-level dry-run preview, batch id, kind selection, normalized id collision checks against the file and existing secrets/aliases, selectable valid rows, and downloadable per-row failure reporting without native browser alert/confirm prompts.
- Audit review supports client-side filters for app, action, status, date range, failed/attempted events, and redaction-safe JSON export.
- Browser autofill is not exposed in Vault. User-directed credential changes go through the controlled add, rotate, and import flows; grant/audit details stay in Advanced/Admin review.
- Sidebar widgets are iframe-mounted app-owned surfaces. They show redaction-safe summary metadata, open Vault with scalar navigation params, and mutate Core Secrets only through admin-gated core APIs, not through app-owned backend actions.
- CLI/MCP agent operations support `manifest`, `diagnose`, `connection_issues`, `plan_fix`, `explain_issue`, and `apply_fix`. `manifest` remains the default for compatibility. Diagnosis and planning consume redaction-safe Core Secrets need payloads or, when available, read the official core recommendation helpers used by the core CLI/MCP surfaces. `apply_fix` only creates app secret grants when a matching saved credential exists, explicit confirmation is present, and the Core Secrets grant surface is available; fixes that require a raw value return `needs_secure_input` and must be completed through platform-owned secure input.
- CLI/MCP manifests distinguish redaction-safe read-only core surfaces from mutative full-access operations and platform-admin HTTP routes. Unsupported Vault actions/tools return error status payloads.
- No app-owned backend, storage, or reference entities are declared.
