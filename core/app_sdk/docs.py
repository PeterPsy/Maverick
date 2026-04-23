"""Embedded documentation for the official Maverick App SDK."""

from __future__ import annotations


SDK_DOCS_MARKDOWN = """# Maverick App SDK

Use the SDK to create, validate, register, install, inspect, and package workspace-local Maverick apps without reading platform source files.

## Required Flow

```bash
maverick sdk templates
maverick sdk docs
maverick app create <app_id> --template <template_id>
maverick app validate <app_id>
maverick app register-local <app_id>
maverick app install-local <app_id>
maverick app status <app_id>
maverick app package <app_id>
```

If `maverick` is unavailable or `maverick sdk templates` fails, stop and report that the SDK runtime surface is unavailable. Do not create apps by copying existing app folders or manually inventing contracts.

## Templates

- `minimal`: contract-first skeleton.
- `frontend-backend`: mounted frontend plus JSON backend.
- `agent-tool`: CLI, MCP, and skill surfaces.
- `data-app`: frontend, backend, CLI, MCP, hooks, and JSON state.
- `widget`: mounted frontend, backend, and widget declaration.
- `react-vite`: React/Vite frontend with mountable `frontend/dist` and official rebuild support.
- `entity-sqlite`: CRM-like SQLite entity app with backend, frontend, CLI, MCP, hooks, references, view surfaces, tests, and official rebuild support.

## Workspace Rules

Generated workspace-local app source lives under `apps/<app_id>` relative to the current workspace. App data belongs under `data/<app_id>`. Creating files is not enough: validate, register, install, and verify status through the SDK lifecycle.

Do not read or write another app's private data. Do not add app-specific core shortcuts. Keep real product behavior inside the app.

## Surface Rules

Do not declare surfaces that are not implemented.

- if the contract declares `capabilities.cli_commands`, the app must expose a real CLI entrypoint and the commands must appear in `maverick app <app_id> cli list --json`
- if the contract declares `capabilities.mcp_tools`, the app must expose a real MCP entrypoint and the tools must appear in `maverick app <app_id> mcp list --json`
- if the contract declares `reference_entities`, the app should implement matching manifest, search, resolve, and summarize behavior through CLI or MCP
- if the contract declares `view_surfaces`, the app should implement real view state actions such as `view_filter`, `set_view_filter`, `set_custom_view`, and `clear_custom_view`
- if the contract declares `lifecycle.rebuild: true`, the app must contain a `package.json` with a `build` script and a declared frontend artifact root

The contract is not documentation-only metadata. It is an executable promise to the rest of Maverick.

## Discovery-First Verification

After registration and installation, verify app surfaces through scoped discovery instead of guessing:

```bash
maverick app <app_id> cli list --json
maverick app <app_id> cli inspect <command_name> --json
maverick app <app_id> mcp list --json
maverick app <app_id> mcp inspect <tool_name> --json
```

Use `--help` only for human syntax help. Use `list` and `inspect` for machine-readable discovery.

## Frontend Rebuild

For buildable frontend templates such as `react-vite` and `entity-sqlite`, publish updated mounted assets through the official rebuild operation:

```bash
maverick app <app_id> frontend build --json
```

That command runs the declared frontend build, verifies the declared artifact root, and emits `maverick.app.frontend-changed` so mounted clients can refresh without a manual page reload.

## App Creation Checklist

1. Pick a lowercase kebab-case app id.
2. Generate with the closest SDK template.
3. Replace scaffold behavior with the requested product behavior.
4. Keep `app_contract.json` aligned with the files that actually exist and the surfaces that actually work.
5. Verify CLI and MCP discovery for every declared executable surface.
6. Run `maverick app validate <app_id>`.
7. Run `maverick app register-local <app_id>`.
8. Run `maverick app install-local <app_id>`.
9. Run `maverick app status <app_id>` and confirm `installed` is true.
10. If the app declares `lifecycle.rebuild: true`, run `maverick app <app_id> frontend build --json`.
11. Package with `maverick app package <app_id>` when an artifact is needed.

## Verification

Use SDK status and scoped Maverick discovery commands. Treat `--help` as human syntax help, not as the machine-readable discovery contract.
"""


def sdk_docs_markdown() -> str:
    """Return the SDK documentation content exposed to workspace runtimes."""
    return SDK_DOCS_MARKDOWN
