# Maverick Monitor

Operator dashboard for machine, workspace, app, process, and Maverick service health.

## Contract Notes

- Frontend, backend, and CLI entrypoints are declared in `app_contract.json`.
- The contract intentionally does not declare MCP tools, bundled skills, or reference entities yet; dashboard view-state is exposed through CLI/backend because Monitor owns lightweight operator preferences.
- Settings state is app-owned under `data/maverick-monitor/state.json`.
- Health checks and migrations are app-owned because the monitor persists operator state even though broader system inspection remains platform-facing.

## SDK Flow

```bash
./scripts/maverick app validate maverick-monitor --workspace default
./scripts/maverick app register-local maverick-monitor --workspace default
./scripts/maverick app install-local maverick-monitor --workspace default
./scripts/maverick app status maverick-monitor --workspace default
./scripts/maverick app package maverick-monitor --workspace default
```
