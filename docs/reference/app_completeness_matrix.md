# App Completeness Matrix

Date: 2026-04-24

This matrix tracks the repository-wide completeness baseline for first-party Maverick apps. The baseline is intentionally narrower than feature parity: it ensures each app has aligned contract metadata, README coverage, and automated smoke coverage, while documenting intentional omissions instead of leaving them implicit.

| App | README | Smoke Coverage | Contract Notes |
| --- | --- | --- | --- |
| `agents` | yes | repo-wide baseline | Bundled `agents-ops` skill now declared in the contract. |
| `app-store` | yes | repo-wide baseline | Bundled `app-store-ops` skill now declared in the contract. |
| `base-shell` | yes | repo-wide baseline | No app-owned backend, hooks, references, or view surface state by design; shell hosting remains a core/platform concern. |
| `chat` | yes | repo-wide baseline | Bundled `chat-ops` skill, thread/project references, standard view state, and shell widgets are declared. |
| `checklist` | yes | app-local contract tests | Repository reference app for complete workspace-stateful contract coverage. |
| `developer-kit` | yes | repo-wide baseline | Frontend-only by design; uses the core-owned `/api/app-sdk` surface instead of app-owned backend, CLI, or MCP. |
| `docs-studio` | yes | repo-wide baseline | Documentation workspace app with declared backend, CLI, MCP, references, view state, and docs-owned storage paths. |
| `document-generator` | yes | repo-wide baseline | Bundled `document-generator-docs` skill, generated-document references, and standard job view state are declared. |
| `dynamic-views` | yes | repo-wide baseline | Bundled `dynamic-views` skill, dynamic-view references, standard library view state, and chat widget are declared. |
| `gallery` | yes | repo-wide baseline plus app-local coverage when present | Bundled `gallery-ops` skill now declared in the contract; file-preview widget remains the embedded surface. |
| `memory` | yes | repo-wide baseline plus app-local coverage when present | Reference app for durable graph state, references, and persisted custom views. |
| `skills` | yes | repo-wide baseline | Contract declares bundled skill template ids, skill references, and standard catalog view state. |
| `user-admin` | yes | repo-wide baseline | Frontend, CLI, and MCP only for now; app-owned backend and hooks remain intentionally absent while admin state stays core-owned. |

The repo-wide automated check for this baseline lives in `tests/test_app_contract_baseline.py`; it now also requires every referenceable app to declare standard view-state actions and matching MCP tools.
