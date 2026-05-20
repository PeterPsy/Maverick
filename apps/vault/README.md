# Vault

Vault is the admin-facing Maverick app for Core Secrets.

It does not own secret values. Secret values remain platform-owned control-plane records under the `core.secrets` domain. Vault calls core HTTP APIs to inspect redaction-safe inventory, grants, and audit metadata from its main frontend. Operational creation/import/grant workflows live in the sidebar widgets and still go through admin-gated core APIs.

## Surfaces

- Frontend: `frontend/dist`
- Widgets:
  - `vault-sidebar` for `base-shell` content kind `shell.sidebar.primary`
  - `vault-sidebar-footer` for `base-shell` content kind `shell.sidebar.footer`
- Backend: none
- CLI: `vault`, a redaction-safe operation manifest that points agents to core-owned secret surfaces
- MCP: `maverick_vault`, the same redaction-safe manifest over MCP
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
- The main frontend is a governance/review surface: it lists and filters secrets, grants, and audit events, but does not create, import, rotate, disable, revoke, or grant secrets.
- Grant creation uses Core Secrets validation for active secrets, enabled and mountable workspace apps, target app `permissions.secrets.read` declarations for `app.backend` logical names, unique non-expired logical names, optional expiry, and the `maverick://app.backend/*` delivery target for backend/CLI/MCP app secrets.
- Sidebar widgets keep only the guided creation/import controls: secret creation, CSV import, and grant creation. Grant creation is guided by the admin-only `/api/secret-grant-targets` surface instead of the generic `/api/apps` registry, and logical names that already have persisted active, non-expired grants for the selected app are hidden before submission. The sidebar does not duplicate the main app's inventory, grant, or audit lists below those forms. CSV import enforces a file-size limit, row-count limit, confirmation prompt, and per-row failure reporting.
- Browser autofill and other user-directed secret actions are not exposed in Vault until a controlled executor exists; Vault creates `app.backend` grants only.
- Sidebar widgets are iframe-mounted app-owned surfaces. They show redaction-safe summary metadata, open Vault with scalar navigation params, and mutate Core Secrets only through admin-gated core APIs, not through app-owned backend actions.
- CLI/MCP manifests distinguish redaction-safe read-only core surfaces from mutative full-access operations and platform-admin HTTP routes. Unsupported Vault actions/tools return error status payloads.
- No app-owned backend, storage, or reference entities are declared.
