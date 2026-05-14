"""Embedded documentation for the official Maverick App SDK."""

from __future__ import annotations


SDK_DOCS_MARKDOWN = """# Maverick App SDK

Use the SDK to create, validate, register, install, inspect, and package workspace-local Maverick apps without reading platform source files.

## Required Flow

```bash
maverick sdk templates
maverick sdk docs
maverick core cli run core.app-sdk.create --app-id <app_id> --template-id <template_id> --json
maverick core cli run core.app-sdk.validate --app-id <app_id> --json
maverick core cli run core.app-sdk.register-local --app-id <app_id> --json
maverick core cli run core.app-sdk.install-local --app-id <app_id> --json
maverick core cli run core.app-sdk.status --app-id <app_id> --json
maverick core cli run core.app-sdk.package --app-id <app_id> --json
```

If `maverick` is unavailable or `maverick sdk templates` fails, stop and report that the SDK runtime surface is unavailable. Do not create apps by copying existing app folders or manually inventing contracts.

## Templates

- `minimal`: contract-first skeleton.
- `frontend-backend`: mounted React/Vite frontend plus JSON backend and official frontend build support.
- `agent-tool`: CLI, MCP, and skill surfaces.
- `data-app`: React/Vite frontend, backend, CLI, MCP, hooks, JSON state, and official frontend build support.
- `widget`: mounted React/Vite frontend, backend, widget declaration, and official frontend build support.
- `react-vite`: React/Vite frontend with mountable `frontend/dist` and official frontend build support.
- `entity-sqlite`: record-centric SQLite entity app with backend, frontend, CLI, MCP, hooks, references, view surfaces, tests, and official frontend build support.

## Workspace Rules

Generated workspace-local app source lives under `apps/<app_id>` relative to the current workspace. App data belongs under `data/<app_id>`. Creating files is not enough: validate, register, install, and verify status through the SDK lifecycle.

Do not read or write another app's private data. Do not add app-specific core shortcuts. Keep real product behavior inside the app.

## Surface Rules

Do not declare surfaces that are not implemented.

- if the contract declares `capabilities.cli_commands`, the app must expose a real CLI entrypoint and the commands must appear in `maverick app <app_id> cli list --json`
- if the contract declares `capabilities.mcp_tools`, the app must expose a real MCP entrypoint and the tools must appear in `maverick app <app_id> mcp list --json`
- if the contract declares `reference_entities`, the app should implement matching manifest, search, resolve, and summarize behavior through CLI or MCP
- if the contract declares `view_surfaces`, the app should implement real view state actions such as `view_filter`, `set_view_filter`, `set_custom_view`, and `clear_custom_view`
- frontend apps must contain a `package.json` with a real `build` script and a declared frontend artifact root; no-op scripts that only check `frontend/dist` do not satisfy the contract
- frontend apps must set `presentation.frontend_role` to `workspace` when the frontend is user-openable, or `supporting` when the frontend only supports a platform/plugin workflow
- if app writes emit `app_events`, mounted frontend and widget surfaces should consume `maverick.app.data-changed` or `maverick.widget.data-changed` so users do not need manual refreshes

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

For frontend templates, publish updated mounted assets through the official rebuild operation:

```bash
maverick app <app_id> frontend build --json
```

That command runs the declared frontend build, verifies the declared artifact root, and emits `maverick.app.frontend-changed` so mounted clients can refresh without a manual page reload.

SDK frontend templates are React/Vite apps. Keep app UI code under `frontend/src`, keep Vite entry HTML files as thin mount documents, and use the SDK-generated `tsc --noEmit && vite build` script for type checking and production assets.

## Live Update Wiring

When an app backend, CLI, or MCP write returns `app_events`, treat that as part of the product contract rather than as optional polish.

- mounted frontends should react to `maverick.app.data-changed`
- widgets should react to `maverick.widget.data-changed`
- shell-mounted apps can consume same-origin `postMessage` forwarding from `base-shell`
- direct mounts can connect to `/api/apps/events/ws`

Do not leave stateful apps in a startup-fetch-only mode if the app already emits live change events.

## App Creation Checklist

1. Pick a lowercase kebab-case app id.
2. Generate with the closest SDK template.
3. Replace scaffold behavior with the requested product behavior.
4. Keep `app_contract.json` aligned with the files that actually exist and the surfaces that actually work.
5. Verify CLI and MCP discovery for every declared executable surface.
6. Run `maverick core cli run core.app-sdk.validate --app-id <app_id> --json`.
7. Run `maverick core cli run core.app-sdk.register-local --app-id <app_id> --json`.
8. Run `maverick core cli run core.app-sdk.install-local --app-id <app_id> --json`.
9. Run `maverick core cli run core.app-sdk.status --app-id <app_id> --json` and confirm `installed` is true.
10. If the app declares a frontend entrypoint, run `maverick app <app_id> frontend build --json`.
11. If the app emits live data-change events, verify the mounted frontend or widget updates without manual refresh.
12. Package with `maverick core cli run core.app-sdk.package --app-id <app_id> --json` when an artifact is needed.

## Verification

Use SDK status and scoped Maverick discovery commands. Treat `--help` as human syntax help, not as the machine-readable discovery contract.
"""


def sdk_docs_markdown() -> str:
    """Return the SDK documentation content exposed to workspace runtimes."""
    return SDK_DOCS_MARKDOWN
