# SDK templates

| Template | Use when |
| --- | --- |
| `minimal` | you need a contract-first skeleton |
| `react-vite` | you need a mounted frontend and domain model is not stable yet |
| `frontend-backend` | you need a React UI plus JSON backend |
| `data-app` | you need JSON state, backend, CLI, MCP, hooks, and frontend |
| `agent-tool` | you need CLI/MCP/skill surfaces without a primary UI |
| `widget` | you primarily contribute an embeddable visual surface |
| `entity-sqlite` | you need record-centric records, references, view state, CLI, MCP, and SQLite |

## Template rule

Generated files are starting source. Replace placeholder behavior with real product behavior before marking an app complete.

## Best default

Use `entity-sqlite` for business entities. Use `data-app` for small structured tools. Use `react-vite` when only the UI is clear.
