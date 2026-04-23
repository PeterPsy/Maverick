# Maverick v3

Maverick is a workspace-isolated AI operating environment for building, running, and extending agent-powered apps.

Maverick v3 is a clean rebuild. It is not a backward-compatible continuation of Maverick v2.

## Status

Maverick v3 is experimental and not production-ready.

Do not expose it to the public internet or store production secrets in it yet. Known security blockers are documented in `SECURITY_AUDIT.md`; open source launch readiness is tracked in `OPEN_SOURCE.md`.

## What Maverick Provides

- headless platform core under `core/`
- workspace-rooted tenant data under `workspaces/<workspace_id>/`
- app-owned workspace data under `workspaces/<workspace_id>/data/<app_id>/`
- contract-driven built-in apps under `apps/`
- sandbox-first runtime policy for non-default workspaces
- provider-backed runtime sessions for agents
- app CLI and MCP discovery surfaces

## Repository Layout

```text
apps/        Built-in app packages and app contracts.
core/        Maverick platform core package root.
docs/        Architecture, SDK, deployment, and security documentation.
scripts/     Developer, verification, and deployment helper scripts.
tests/       Python test suite.
workspaces/  Workspace-owned runtime and app data roots.
```

The `core/` directory is the direct Python package root. Do not wrap it in `backend/`, `runtime_backend/`, `app/`, or `core/core/`.

## Requirements

- Python 3.12
- Node.js and npm for frontend app builds
- Linux with `bubblewrap` for workspace sandbox verification
- Codex CLI if you want to run Codex-backed agents
- MongoDB for the hosted control-plane persistence path

The current local bootstrap can run core tests without MongoDB, but a full hosted environment needs the persistence and deployment pieces documented in `docs/deployment/local_setup.md`.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
# Alternatively: python3 -m pip install -r requirements-dev.txt

python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall core tests scripts
python3 scripts/check_unused_imports.py
```

To run the ASGI host locally:

```bash
uvicorn core.api.asgi_application:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/health`.

## Frontend Apps

Some built-in apps commit `frontend/dist/` so they can mount without a build step. Apps with frontend source and a `package-lock.json` can be rebuilt from their app directory:

```bash
cd apps/chat
npm ci
npm run build
```

Generated artifact policy is documented in `docs/development/generated_artifacts.md`.

## Skills

Maverick product skills are app-owned extension data.

Bundled skill templates live under `apps/skills/skills/`. The Skills app copies workspace-owned skill templates into `workspaces/<workspace_id>/data/skills/skills/`.

Maverick runtime sessions do not rely on `~/.codex/skills`, plugin skills, or repository `local-skills/` directories.

## Architecture Docs

Read these before changing structure or implementation:

- `docs/architecture/core_architecture.md`
- `docs/architecture/workspace_root_architecture.md`
- `docs/architecture/app_contract_architecture.md`
- `IMPLEMENTATION_TASKLIST.md`

If code and docs disagree, fix the disagreement in the same change.

## Security

Read `SECURITY.md` before testing or deploying Maverick.

Important current limitations:

- local bootstrap secrets are not a production secret backend
- app frontend and backend isolation is still being hardened
- public internet deployment is not supported
- recovery automation and runtime provider policies need additional production gates

## Contributing

Read `CONTRIBUTING.md`, `GOVERNANCE.md`, and `CODE_OF_CONDUCT.md`.

Use public issues for reproducible bugs and docs gaps after the repository is public. Use the private security process in `SECURITY.md` for vulnerabilities.

## License

Maverick is released under the MIT License. See `LICENSE`.
