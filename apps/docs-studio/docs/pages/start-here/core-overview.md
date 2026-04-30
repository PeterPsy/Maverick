# Core overview

> **Read this first.** Maverick is a clean rebuild: the core is the platform host, while apps own product behavior and workspace data.

## At a glance

| Layer | Owns | Must not own |
| --- | --- | --- |
| Core | Identity, workspaces, app hosting, runtime, providers, execution policy, secrets, recovery, logs, CLI, MCP | App data, app schemas, business workflows |
| Apps | UI, backend behavior, CLI/MCP tools, lifecycle hooks, skills, app-owned data | Core control-plane state, other apps' private data |
| Workspace | Editable app projects, generated files, uploads, app data, tests, runtime state | Installation-level source or other workspaces |

## Design rule

- Keep `core/` headless, app-agnostic, and platform-scoped.
- Keep app behavior inside `apps/<app_id>` or workspace-local `apps/<app_id>`.
- Keep durable app content under `data/<app_id>`.
- Use official core surfaces for cross-boundary work: CLI, MCP, HTTP, runtime, or shell APIs.

## Decision standard

Choose the implementation that is easiest to read, test, delete, and align with the architecture docs.


## Operating model

Maverick works best when every change starts by asking which layer owns the behavior. Core changes should improve platform capability for every app. App changes should improve one product surface without teaching the core about that product.

### Ownership questions

| Question | If yes | Owner |
| --- | --- | --- |
| Does this affect identity, workspace access, app hosting, runtime, providers, secrets, or recovery? | It is a platform concern | Core |
| Does this define a user-facing workflow, record type, view, or persisted business state? | It is product behavior | App |
| Does this move information between products? | Use references, widgets, CLI, MCP, or runtime orchestration | Core surface plus owning app |

## Practical example

Docs Studio owns documentation pages and the reading experience. The core only knows that Docs Studio is installed, enabled, has a frontend, exposes declared CLI/MCP tools, and stores data under `data/docs-studio`.
