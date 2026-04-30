# Frontend and backend

## Frontend source

SDK-generated frontend apps use React/Vite:

```text
frontend/index.html
frontend/src/
frontend/dist/
```

The contract points to `frontend/dist`. The source lives in `frontend/src`.

## Frontend build

```bash
npm run build
maverick app <app_id> frontend build --json
```

The Maverick build command verifies the artifact root and emits `maverick.app.frontend-changed`.

## Backend shape

App backend entrypoints are JSON stdin/stdout scripts executed by the core. Keep them thin:

- read entrypoint payload
- dispatch by action
- call service logic
- return `{"status_code": 200, "json": {...}}`

Mounted frontends call their own backend at:

```text
/api/apps/<app_id>/backend
```
