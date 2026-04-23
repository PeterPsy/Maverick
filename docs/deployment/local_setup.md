# Local Setup

This guide describes the public clean-clone path for Maverick v3.

Maverick is experimental. Use fake data and local-only networking.

## Prerequisites

- Python 3.12
- Node.js and npm
- `bubblewrap` on Linux for sandbox tests
- Codex CLI for Codex-backed runtime sessions
- MongoDB for hosted control-plane persistence

For the first public release, the recommended path is local CLI-first setup, not Docker and not a setup UI.

## Installer CLI

For a fresh install, use the installer CLI:

```bash
python3 scripts/install_maverick.py
```

The default flow is interactive. It:

- asks for the missing deployment values
- bootstraps the Python environment
- runs the core verification suite
- renders systemd units under `.maverick/install/systemd/`
- renders nginx config under `.maverick/install/nginx/`
- writes `.maverick/install/install-manifest.json`
- offers to apply the rendered plan to systemd and nginx
- offers to request a TLS certificate with `certbot` for public `https` installs
- runs final health checks

For a non-interactive public install with defaults accepted:

```bash
python3 scripts/install_maverick.py --hostname maverick.example.com --yes
```

For a local-only install without nginx or TLS:

```bash
python3 scripts/install_maverick.py --local-only
```

Use `--render-only` when you only want the generated files without changing the live system.

Use `--install-root`, `--service-user`, `--service-group`, `--core-port`, `--rescue-port`, `--bind-host`, `--output-root`, `--systemd-dir`, `--nginx-conf`, `--live-systemd-dir`, `--live-nginx-conf`, `--live-nginx-enabled`, and `--acme-root` to customize the flow.

## Python Environment

```bash
./scripts/bootstrap_local.sh
source .venv/bin/activate
```

## Verify Core

```bash
./scripts/verify_local.sh
```

## Run Core Host

```bash
./scripts/run_local.sh
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Frontend Apps

Apps with source are built from their app directories:

```bash
cd apps/chat
npm ci
npm run build
```

Apps that only verify `frontend/dist/index.html` are using committed built artifacts. See `docs/development/generated_artifacts.md`.

To build every app frontend during bootstrap:

```bash
MAVERICK_BUILD_FRONTENDS=1 ./scripts/bootstrap_local.sh
```

## Environment Variables

Copy `.env.example` only as a local starting point. Do not commit `.env`.

Production-quality secret storage is not implemented yet. Do not put production OAuth credentials or API keys into the local bootstrap environment.

## CLI Discovery

Use the checked-in wrapper for machine-readable discovery:

```bash
./scripts/maverick apps list --json
./scripts/maverick core cli list --json
./scripts/maverick core mcp list --json
./scripts/maverick core cli run developer-context.list --json
```

## Persistence

The repository contains the directory layout for workspace-owned data. Runtime, app data, and local bootstrap state must not be committed.

Use fake local data until the production persistence and secret-storage hardening work is complete.
