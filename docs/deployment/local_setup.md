# Local Setup

This guide describes the public clean-clone path for Maverick v3.

Maverick is experimental. Use fake data and local-only networking.

## Prerequisites

- Python 3.12
- Node.js and npm
- `bubblewrap` on Linux for sandbox tests
- Codex CLI for Codex-backed runtime sessions
- MongoDB for hosted control-plane persistence

## Python Environment

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
```

## Verify Core

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall core tests scripts
python3 scripts/check_unused_imports.py
```

## Run Core Host

```bash
uvicorn core.api.asgi_application:app --host 127.0.0.1 --port 8000
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

## Environment Variables

Copy `.env.example` only as a local starting point. Do not commit `.env`.

Production-quality secret storage is not implemented yet. Do not put production OAuth credentials or API keys into the local bootstrap environment.

## Persistence

The repository contains the directory layout for workspace-owned data. Runtime, app data, and local bootstrap state must not be committed.

Use fake local data until the production persistence and secret-storage hardening work is complete.
