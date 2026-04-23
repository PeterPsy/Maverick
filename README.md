# Maverick v3

Maverick is a workspace-isolated AI operating environment for building, running, and extending agent-powered apps.

Maverick v3 is a clean rebuild. It is not a backward-compatible continuation of Maverick v2.

Public launch description:

Maverick is an experimental open source, self-hostable platform for workspace-isolated agent apps, not a production-ready hosted service.

## Status

Maverick v3 is experimental and not production-ready.

Do not expose it to the public internet or store production secrets in it yet. Known security blockers are documented in `SECURITY_AUDIT.md`; open source launch readiness is tracked in `OPEN_SOURCE.md`; the first-release execution plan is tracked in `OPEN_SOURCE_CHECKLIST.md`.

## What Maverick Provides

- headless platform core under `core/`
- workspace-rooted tenant data under `workspaces/<workspace_id>/`
- app-owned workspace data under `workspaces/<workspace_id>/data/<app_id>/`
- contract-driven built-in apps under `apps/`
- sandbox-first runtime policy for non-default workspaces
- provider-backed runtime sessions for agents
- app CLI and MCP discovery surfaces

## What Maverick Is Not

Maverick is not yet:

- a production-safe deployment target
- a hosted SaaS service
- a hardened internet-facing multi-tenant platform
- a backward-compatible Maverick v2 migration layer
- a trusted third-party app execution platform

## Current Limitations

- security hardening remains incomplete for internet-facing or sensitive deployments
- production secret storage is not implemented yet
- provider-backed agent execution currently assumes Codex for the real runtime path
- deployment guidance is suitable for evaluation, not for production endorsement
- setup is intentionally CLI-first in this phase; a setup UI is planned later

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
./scripts/bootstrap_local.sh
source .venv/bin/activate
./scripts/verify_local.sh
```

To run the ASGI host locally:

```bash
./scripts/run_local.sh
```

Then open `http://127.0.0.1:8000/health`.

## Frontend Apps

Some built-in apps commit `frontend/dist/` so they can mount without a build step. Apps with frontend source and a `package-lock.json` can be rebuilt from their app directory:

```bash
cd apps/chat && npm ci && npm run build
```

Generated artifact policy is documented in `docs/development/generated_artifacts.md`.

## Skills

Maverick product skills are app-owned extension data.

Bundled skill templates live under app-owned source directories such as `apps/skills/skills/` and `apps/<app_id>/skills/`. The Skills app copies workspace-owned skill templates into `workspaces/<workspace_id>/data/skills/skills/`.

Maverick runtime sessions do not rely on `~/.codex/skills`, plugin skills, or repository `local-skills/` directories.

## Docs Map

Start here:

- `docs/deployment/local_setup.md`
- `docs/deployment/self_hosted_evaluation.md`
- `docs/security/threat_model.md`
- `docs/reference/core_surfaces.md`
- `docs/reference/runtime_provider_model.md`
- `docs/reference/persistence_model.md`

Architecture source of truth:

- `docs/architecture/core_architecture.md`
- `docs/architecture/workspace_root_architecture.md`
- `docs/architecture/app_contract_architecture.md`
- `IMPLEMENTATION_TASKLIST.md`

Decision summaries:

- `docs/adr/README.md`

Open source launch and roadmap:

- `OPEN_SOURCE.md`
- `OPEN_SOURCE_CHECKLIST.md`
- `ROADMAP.md`

If code and docs disagree, fix the disagreement in the same change.

## Security

Read `SECURITY.md` before testing or deploying Maverick.

Important current limitations:

- local bootstrap secrets are not a production secret backend
- app frontend and backend isolation is still being hardened
- public internet deployment is not supported
- recovery automation and runtime provider policies need additional production gates
- production secret storage is not implemented yet

## Contributing

Read `CONTRIBUTING.md`, `GOVERNANCE.md`, and `CODE_OF_CONDUCT.md`.

Use public issues for reproducible bugs and docs gaps after the repository is public. Use the private security process in `SECURITY.md` for vulnerabilities.

## License

Maverick is released under the MIT License. See `LICENSE`.
