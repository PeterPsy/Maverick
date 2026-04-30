# Workspace isolation

## Default workspace

The `default` workspace is the privileged operator workspace. It may run with full access when platform and workspace governance allow it.

## Non-default workspaces

- Always sandboxed.
- Readable roots and writable roots equal the workspace root.
- No direct access to installation-level `core/`, installation-level `apps/`, or sibling workspaces.
- Cross-workspace work must happen through explicit product features.

## Failure behavior

If the platform cannot enforce sandbox boundaries for a non-default workspace, runtime launch should fail closed.


## Boundary invariants

- A sandboxed runtime cannot read or write outside its workspace root.
- Gallery and retrieval must never return another workspace's files.
- Child agents inherit the same workspace root unless a trusted control-plane action changes scope.
- Platform interaction from sandboxed workspaces goes through controlled interfaces.

## Why this matters

The workspace root should feel like a complete private operating environment. That is simpler than scattering state across runtime workdirs, backend-only storage, and global indexes.
