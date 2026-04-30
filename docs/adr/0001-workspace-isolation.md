# ADR-0001: Workspace Isolation

## Status

Accepted

## Context

Maverick must support workspace-scoped agent execution without granting every runtime session access to the full host or repository tree.

## Decision

- `workspaces/<workspace_id>/` is the tenant root for workspace-owned material.
- non-default workspaces are sandbox-first by policy
- app-owned data must live under `workspaces/<workspace_id>/data/<app_id>/`
- runtime sessions should read canonical developer context through core-owned surfaces rather than raw repository access

## Consequences

- workspace-local behavior is easier to reason about
- sandbox policy becomes a core product requirement rather than a prompt convention
- setup and docs must distinguish between trusted repo development and workspace-bounded agent execution
