# Contributing to Maverick

Maverick v3 is a clean-slate rebuild. Contributions should make the platform easier to read, test, delete, and secure.

## Project Status

Maverick is experimental and not production-ready. Security-critical work is tracked in `SECURITY_AUDIT.md` and launch readiness is tracked in `OPEN_SOURCE.md`.

## Before You Change Code

Read the source-of-truth documents:

- `docs/architecture/core_architecture.md`
- `docs/architecture/workspace_root_architecture.md`
- `docs/architecture/app_contract_architecture.md`
- `IMPLEMENTATION_TASKLIST.md`

If implementation and documentation disagree, fix the disagreement in the same change.

## Development Setup

Use Python 3.12. A minimal local setup is:

```bash
./scripts/bootstrap_local.sh
source .venv/bin/activate
```

Frontend apps with source have their own `package-lock.json`; install and build them from each app directory.

The first public release is intentionally CLI-first. A built-in setup or onboarding UI is deferred until the setup path and public docs stabilize.

## Verification

Run the smallest relevant checks for your change. For broad changes, run:

```bash
./scripts/verify_local.sh
```

For frontend app changes, run the app's local `npm run build` and `npm test` if present.

## Code Standards

- Keep `core/` as the direct package root.
- Keep app data under `workspaces/<workspace_id>/data/<app_id>/`.
- Keep platform infrastructure outside workspace roots.
- Prefer small domain-oriented files.
- Do not introduce compatibility shims for v2.
- Do not leave dead code, commented-out code, placeholder branches, or unused scaffolding.
- Keep persistence details inside store adapters and bootstrap wiring.
- Do not leak raw database payloads into domain models or service interfaces.

## Documentation Standards

Update docs in the same change when you modify:

- architecture
- package boundaries
- runtime behavior
- app contracts
- workspace behavior
- security policy
- setup or deployment

Do not use TODO comments as a substitute for updating docs.

## Pull Requests

Every PR should include:

- what changed
- why it changed
- how it was tested
- documentation updates, or a clear reason none were needed
- security implications for runtime, workspace, app, or secret handling

Keep PRs focused. Do not mix unrelated refactors with feature or security work.

## AI-Assisted Contributions

AI-assisted code is allowed, but contributors are responsible for correctness, licensing, tests, and maintainability. Do not submit generated code that you cannot explain or maintain.

## Vulnerabilities

Do not report vulnerabilities in public issues. Follow `SECURITY.md`.

## Docs To Read First

For public release work and architecture-sensitive changes, start with:

- `docs/security/threat_model.md`
- `docs/adr/README.md`
- `docs/reference/core_surfaces.md`
- `docs/reference/runtime_provider_model.md`
- `docs/reference/persistence_model.md`
- `OPEN_SOURCE_CHECKLIST.md`
