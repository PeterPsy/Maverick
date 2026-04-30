# Maverick

Maverick is an AI agentic operating system for companies that want to delegate real digital work to AI agents without losing ownership, boundaries, or extensibility.

Most business operations are fragmented across SaaS tools, documents, inboxes, internal dashboards, scripts, credentials, and one-off automations. AI makes that fragmentation more visible: an agent can reason across work, but it still needs a governed place to discover tools, access the right workspace data, use approved providers, call app surfaces, and leave an auditable trail.

Maverick is that place. It gives teams a workspace-isolated platform where apps, widgets, skills, providers, databases, CLI commands, and MCP tools are first-class building blocks for agentic operations.

The goal is not to add another chat box on top of existing software. The goal is to make operational delegation practical: an AI agent should be able to understand the current workspace, use the right app, call the right tool, create or update the right data, and hand control back to humans when policy requires it.

Maverick is for teams building internal AI operations, agent-native business tools, self-hosted automation platforms, or company-specific AI workspaces.

Maverick is not production-ready yet. Use it for local evaluation, development, and architecture review. Do not expose it to the public internet or store production secrets in it until the security roadmap is complete.

## Principles

### Delegation over chat

Chat is only one interface. Maverick treats AI as an operator that can work through apps, widgets, CLI commands, MCP tools, provider runtimes, and workspace-owned skills.

### Workspace isolation first

Company work needs boundaries. Maverick keeps workspace-owned data, app data, runtime material, generated files, logs, and policy decisions scoped to the workspace they belong to.

### Maximum AI extensibility

Every important platform surface should be discoverable and invokable by agents through explicit contracts. Apps declare their capabilities. Core and apps expose scoped CLI/MCP surfaces. Skills are workspace-owned. The App SDK exists so new tools can be created without changing the core.

### Core stays app-agnostic

The core owns platform concerns: identity, sessions, workspaces, app mounting, runtime orchestration, provider selection, persistence adapters, secrets, recovery, and governance. App-specific behavior belongs in apps.

### Apps own product behavior

Apps own their UI, backend actions, widgets, references, data model, lifecycle hooks, and workspace data. The platform mounts and governs apps through contracts instead of importing app internals.

### Provider and database independence

Maverick should not be defined by one model provider or one database. Codex is the default runtime backend today, JSON is the default control-plane adapter, and MongoDB is optional. The architecture is designed for more providers and adapters over time.

### Rebuildable operating state

Installation-local operating material should be rebuildable. Durable control-plane data and workspace-owned app data must not depend on `.maverick`.

### Human governance remains explicit

Agents should be powerful, but not invisible. Maverick favors explicit permissions, workspace policy, recoverable operator flows, scoped secrets, and auditable platform surfaces.

## Install

Maverick is easiest to evaluate from a clean clone. The default setup is intentionally local and CLI-first: it gives you the platform core, bundled apps, JSON persistence, and a local ASGI host without requiring MongoDB or external infrastructure.

### Requirements

- Linux
- Python 3.12, including the `venv` package
- Node.js and npm
- `bubblewrap` for sandbox verification
- Codex CLI for the default Codex-backed runtime path
- MongoDB only if you choose the MongoDB control-plane adapter

The default control-plane adapter is JSON. A new install does not require MongoDB.

On Ubuntu, install Python 3.12 support with:

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv
```

### Local Evaluation

Use this path when you want to try Maverick as a developer without installing system services:

```bash
git clone https://github.com/PeterPsy/Maverick.git maverick
cd maverick

./scripts/bootstrap_local.sh
source .venv/bin/activate
./scripts/verify_local.sh
./scripts/run_local.sh
```

In another terminal, check that the core is alive:

```bash
curl http://127.0.0.1:8000/health
```

Most committed app frontend artifacts are already present. If you want to rebuild app frontends as part of bootstrap:

```bash
./scripts/bootstrap_local.sh --build-frontends
```

### Local Service Install

Use the installer when you want Maverick to behave more like a local service. It renders service files, local environment files, bootstrap secret refs, and an install manifest from one repeatable operator flow:

```bash
python3.12 scripts/install_maverick.py --local-only
```

You can inspect the generated plan without applying it:

```bash
python3.12 scripts/install_maverick.py --local-only --render-only
```

### Hosted Evaluation

For a hostname-backed evaluation machine, run the installer with a public host:

```bash
python3.12 scripts/install_maverick.py --hostname maverick.example.com
```

The installer can render and optionally apply systemd units, nginx configuration, and TLS setup. Keep this path for evaluation until the security roadmap says otherwise.

### Persistence Choice

Maverick starts with JSON because it keeps the first install simple and portable:

```bash
python3.12 scripts/install_maverick.py --control-store json
```

Use MongoDB when you want the control plane in a database service instead of local JSON collections:

```bash
python3.12 scripts/install_maverick.py \
  --control-store mongo \
  --mongodb-uri mongodb://127.0.0.1:27017/maverick
```

When MongoDB authentication is enabled, the installer asks for the password once and stores it as an encrypted bootstrap secret. The rendered environment file contains only `MAVERICK_MONGODB_PASSWORD_REF`.

The selected adapter owns platform control-plane data such as users, sessions, workspace registry, workspace membership, app bindings, provider selections, runtime token metadata, and secret metadata/value envelopes.

`.maverick` is only rebuildable operating material. Deleting it should not delete users, workspace memberships, app bindings, provider/OAuth bindings, runtime token records, secret values, or workspace-owned app data.

### Admin Password

Maverick treats the admin password as an identity credential, not as a long-lived boot secret. A normal install should not keep a plaintext admin password in `.env` or `.maverick`.

After install, set or recover the admin password through the operator CLI:

```bash
maverick core cli run core.identity.reset-admin-password \
  --username admin \
  --password '<new-password>' \
  --json
```

That command writes only the password hash to the durable identity store and revokes existing sessions for the admin user.

## What Maverick Provides

Maverick is built from a few simple pieces that stay separate on purpose. The core governs the platform. Workspaces hold tenant state. Apps own product behavior. Agents interact with all of it through explicit, discoverable surfaces.

### Core

`core/` is the platform package root. It is intentionally headless and app-agnostic.

It owns identity, sessions, workspace registry, app registration, app mounting, runtime orchestration, provider selection, persistence adapters, secret handling, recovery surfaces, and platform HTTP/CLI/MCP APIs.

If a behavior is specific to one app, it belongs in that app. The core should provide generic surfaces that many apps can use.

### Workspaces

A workspace is the boundary around a company's or team's operating context. It is where app-owned data, runtime material, logs, uploads, generated files, and workspace-local apps belong.

Workspace data lives under:

```text
workspaces/<workspace_id>/
```

App-owned persistent data lives under:

```text
workspaces/<workspace_id>/data/<app_id>/
```

The `workspaces/` directory is generated at bootstrap/runtime and should not be treated as source code.

### Apps

Apps are how Maverick grows. A CRM, memory graph, gallery, chat surface, admin panel, document workflow, or company-specific tool should be an app, not a core patch.

Apps live under `apps/<app_id>/` and are described by `app_contract.json`.

An app can provide frontend, backend, CLI, MCP, lifecycle hooks, widgets, skills, reference entities, view surfaces, and storage behavior. Apps own their domain data and UI. The platform mounts and governs them through the app contract.

### Widgets

Widgets let one app show a small, focused surface inside another app without breaking ownership. Chat can render a checklist widget, for example, without importing the checklist app's source code.

Widget context is explicit and signed by the core before the iframe is mounted.

### Runtime Agents And Skills

Maverick can run provider-backed agent sessions inside workspace-aware runtime roots.

Skills are the operating instructions that make agents more useful inside a specific workspace. They are managed by the Skills app and stored as workspace-owned data.

Bundled skill templates can be seeded from app source, but agents consume the workspace copy under:

```text
workspaces/<workspace_id>/data/skills/skills/
```

Maverick runtime sessions do not rely on user-global `~/.codex/skills`, plugin skills, or repository-local skill folders.

### Provider Agnostic

Maverick should not force a company into one AI backend. The provider model is adapter-based.

Codex is the default concrete runtime backend today, but the architecture separates provider definitions, credential bindings, workspace provider selection, runtime launch, and runtime execution.

Future providers should fit behind the provider/runtime adapter boundary without changing the app model.

### Database Agnostic

Maverick should not force one database either. The control plane is adapter-based.

Supported adapters today:

- JSON, default for clean local installs
- MongoDB, optional for hosted evaluation

The domain model should not leak adapter-specific types. MongoDB documents, JSON files, and future stores should stay behind store adapters and bootstrap wiring.

Adapter migration is a core-owned operator workflow. Exactly one control-plane adapter should be mounted after cutover.

### CLI And MCP

Maverick is designed for both humans and agents. CLI and MCP surfaces are first-class, scoped, and discoverable.

Core commands:

```bash
maverick core cli list --json
maverick core cli inspect <command_id> --json
maverick core cli run <command_id> --json
```

App commands:

```bash
maverick apps list --json
maverick app <app_id> cli list --json
maverick app <app_id> cli inspect <command_name> --json
maverick app <app_id> cli run <command_name> --json
```

Core MCP tools:

```bash
maverick core mcp list --json
maverick core mcp inspect <tool_name> --json
maverick core mcp call <tool_name>
```

App MCP tools:

```bash
maverick app <app_id> mcp list --json
maverick app <app_id> mcp inspect <tool_name> --json
maverick app <app_id> mcp call <tool_name>
```

This scoped discovery model keeps agents from loading every app and platform surface at once.

### App SDK

The App SDK is the path for extending Maverick without copying an existing app or weakening the core boundary. It provides creation, validation, registration, installation, status, packaging, and frontend build surfaces.

```bash
maverick core cli run core.app-sdk.create --app-id <app_id> --template-id <template_id> --json
maverick core cli run core.app-sdk.validate --app-id <app_id> --json
maverick core cli run core.app-sdk.register-local --app-id <app_id> --json
maverick core cli run core.app-sdk.install-local --app-id <app_id> --json
maverick app <app_id> frontend build --json
```

## Repository Layout

The repository is intentionally small at the top level. Source lives in `apps/`, `core/`, `docs/`, `scripts/`, and `tests/`.

```text
.github/     GitHub workflows and repository metadata.
apps/        Built-in app packages and app contracts.
core/        Maverick platform core package root.
docs/        Architecture, SDK, deployment, security, and reference docs.
scripts/     Developer, verification, install, and deployment helpers.
tests/       Python test suite.
```

Generated local/runtime directories such as `workspaces/`, `data/`, `logs/`, `.maverick/`, and `.venv/` are not source directories.

## Frontend Apps

Some built-in apps commit `frontend/dist/` so a clean checkout can mount them without a frontend build step.

To rebuild one app frontend:

```bash
cd apps/chat
npm ci
npm run build
```

When the platform host is running, prefer the official core frontend build surface:

```bash
maverick app chat frontend build --json
```

Generated artifact policy is documented in `docs/development/generated_artifacts.md`.

## Documentation

If you are new to the codebase, start with the deployment and reference docs:

- `docs/deployment/local_setup.md`
- `docs/deployment/self_hosted_evaluation.md`
- `docs/security/threat_model.md`
- `docs/reference/persistence_model.md`
- `docs/reference/runtime_provider_model.md`
- `docs/reference/core_surfaces.md`

Architecture source of truth:

- `docs/architecture/core_architecture.md`
- `docs/architecture/workspace_root_architecture.md`
- `docs/architecture/app_contract_architecture.md`

For project status and contribution expectations:

- `ROADMAP.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `GOVERNANCE.md`

If code and docs disagree, fix the disagreement in the same change.

## Current Limitations

Maverick is moving toward a self-hostable platform for real company operations, but this repository is still pre-production software. The important limits are explicit:

- Maverick is experimental and not production-ready.
- Public internet deployment is not supported for sensitive use.
- Security hardening remains incomplete.
- App frontend/backend isolation is still being hardened.
- Production secret handling is still evolving.
- Codex is the only fully exercised runtime backend today.
- Docker and setup UI flows are not the recommended first public install path yet.

## License

Maverick is released under the MIT License. See `LICENSE`.
