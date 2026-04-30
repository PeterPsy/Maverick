# Cross-app boundaries

## Do

- Store only stable app references when pointing at another app's entity.
- Resolve references through the owning app's official CLI or MCP tools.
- Embed widgets through the core registry and controlled iframe mount.
- Let agents orchestrate multi-app work through official surfaces.

## Do not

- Import another app's source tree.
- Read another app's private `data/<app_id>` store.
- Call another app's private backend internals.
- Add core branches like `if app_id == "some-app"`.

> **Ownership model:** chat owns transcripts, gallery owns files, memory owns notes, Docs Studio owns docs pages.


## Composition patterns

| Need | Use |
| --- | --- |
| Link to a record owned by another app | Reference entity |
| Render another app's visual surface | Widget registry and iframe mount |
| Ask another app to perform a command | Scoped CLI or MCP |
| Coordinate multiple app workflows | Runtime/agent orchestration |

## Widget rule

The embedding app owns the container. The widget owner owns rendering, actions, and persisted widget state. The core owns registry, routing, auth, workspace context, and enablement.
