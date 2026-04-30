# App hosting

## Source versus installation

| Concept | Meaning |
| --- | --- |
| Source | App project or artifact with an `app_contract.json` |
| Registration | Core knows the source exists and validates it |
| Installation | Workspace has a binding to the app source |
| Enablement | App surfaces are mountable and discoverable |

## Workspace-local flow

```bash
maverick core cli run core.app-sdk.create --app-id docs-studio --template-id data-app --json
maverick core cli run core.app-sdk.validate --app-id docs-studio --workspace default --json
maverick core cli run core.app-sdk.register-local --app-id docs-studio --workspace default --json
maverick core cli run core.app-sdk.install-local --app-id docs-studio --workspace default --json
maverick core cli run core.app-sdk.status --app-id docs-studio --workspace default --json
```

## Rules

- Do not hardcode app ids in core.
- Do not copy store apps into workspaces unless forking is explicit.
- Keep app source and app data separate.
- Treat `frontend/dist`, backend, CLI, MCP, hooks, and skills as declared contract surfaces.


## Distribution modes

| Mode | Source access | Typical use |
| --- | --- | --- |
| `sealed` | none | Packaged platform or commercial app |
| `source_available` | read-only or forkable | Store app that can be inspected or forked |
| `workspace_local` | editable | App born inside one workspace |

## Installation is not deletion

Uninstalling an app removes the active workspace binding. It should not silently delete `data/<app_id>`. Data purge is a separate explicit operation.

## Frontend lifecycle

Apps with source-buildable frontends should support:

```bash
maverick app <app_id> frontend build --json
```
