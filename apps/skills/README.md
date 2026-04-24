# Skills

Workspace app for creating, editing, validating, and deleting workspace-owned Codex skills.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled skill template ids copied by the Skills app into workspace-owned skill data: `generate-image`, `maverick-v3-app-creator`, `maverick-v3-app-porting`, `maverick3-code-skill`, and `skills-ops`.
- `skill` is the current reference entity and app-owned state lives under `data/skills/`.
- Persisted `view_surfaces` cover catalog filters and curated skill selections.

## SDK Flow

```bash
./scripts/maverick app validate skills --workspace default
./scripts/maverick app register-local skills --workspace default
./scripts/maverick app install-local skills --workspace default
./scripts/maverick app status skills --workspace default
./scripts/maverick app package skills --workspace default
```
