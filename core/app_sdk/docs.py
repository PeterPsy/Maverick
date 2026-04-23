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
- `react-vite`: React/Vite frontend with mountable `frontend/dist`.
- `entity-sqlite`: CRM-like SQLite entity app with backend, frontend, CLI, MCP, hooks, references, and tests.

## Workspace Rules

Generated workspace-local app source lives under `apps/<app_id>` relative to the current workspace. App data belongs under `data/<app_id>`. Creating files is not enough: validate, register, install, and verify status through the SDK lifecycle.

Do not read or write another app's private data. Do not add app-specific core shortcuts. Keep real product behavior inside the app.

## App Creation Checklist

1. Pick a lowercase kebab-case app id.
2. Generate with the closest SDK template.
3. Replace scaffold behavior with the requested product behavior.
4. Keep `app_contract.json` aligned with the files that actually exist.
5. Run `maverick app validate <app_id>`.
6. Run `maverick app register-local <app_id>`.
7. Run `maverick app install-local <app_id>`.
8. Run `maverick app status <app_id>` and confirm `installed` is true.
9. Package with `maverick app package <app_id>` when an artifact is needed.

## Verification

Use SDK status and scoped Maverick discovery commands. Treat `--help` as human syntax help, not as the machine-readable discovery contract.
"""


def sdk_docs_markdown() -> str:
    """Return the SDK documentation content exposed to workspace runtimes."""
    return SDK_DOCS_MARKDOWN
