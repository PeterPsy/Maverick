# Persistence Model

## Control Plane vs App Data

Maverick separates platform control-plane state from app-owned workspace data.

### Control plane

Control-plane state belongs to the platform core and includes:

- users
- sessions
- workspace registry
- workspace memberships
- governance
- quotas
- app installation and binding state
- runtime process and session metadata
- provider metadata
- secret metadata

### App-owned workspace data

App-owned persistent data belongs under:

```text
workspaces/<workspace_id>/data/<app_id>/
```

Examples:

- chat data
- CRM data
- memory data
- gallery state
- Skills app workspace skill copies

## Workspace Roots

Workspace-owned material belongs under:

```text
workspaces/<workspace_id>/
```

This includes:

- app-owned data
- workspace-local apps
- uploaded files
- generated files
- logs
- runtime-local state

## MongoDB

The hosted control-plane persistence path assumes MongoDB.

That does not change the architectural boundary:

- domain models should remain persistence-agnostic
- raw database details should stay inside store adapters

## First Public Release Position

Persistence is adequate for evaluation and development review, but not yet a finished production story.

The public docs should continue to treat production hardening and secret handling as incomplete work.
