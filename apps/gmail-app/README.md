# Gmail App

Gmail App is a built-in Maverick v3 app for Google Workspace Gmail relationship workflows.

It lets a workspace user search and review Gmail threads, create relationship suggestions, expose Gmail threads/messages as durable references for other apps, prepare replies, and send email only after explicit approval.

## Data Boundary

Workspace data belongs under:

```text
workspaces/<workspace_id>/data/gmail-app/
```

The app creates:

- `gmail.sqlite`
- `state.json`

OAuth access tokens, refresh tokens, and Google client secrets must not be stored in this directory. The app persists only account metadata and secret references. Raw credentials belong in Maverick core secrets once the production OAuth flow is enabled.

## Current MVP

Implemented:

- Google Workspace OAuth authorization-code login from the app UI
- app contract
- backend
- MCP
- CLI
- lifecycle hooks
- operator frontend
- app skill
- SQLite store
- fake Gmail client for deterministic local use and tests
- minimal HTTP Gmail adapter for access-token-backed API calls
- explicit send approval before every send
- generic Gmail reference provider for `thread` and `message` entities

Deferred:

- persistent app-scoped refresh-token storage through core secrets
- native Gmail drafts
- attachments
- bulk send
- autonomous cross-app persistence

## Google Workspace Setup Notes

Use a company-owned Google Cloud project and, where possible, an internal Google Workspace OAuth app.

Evaluate least-privilege Gmail scopes for the enabled features:

- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/gmail.send`
- `https://www.googleapis.com/auth/gmail.compose` only if native Gmail draft creation is enabled

Avoid `https://mail.google.com/` unless a later written decision proves it is required.

Gmail read scopes can be restricted and may require Google verification or security assessment for production use.

The current UI uses a browser-session OAuth flow. The Google OAuth client id, client secret, and access token are kept in `sessionStorage` for the active browser session and are not written to `data/gmail-app`. Long-lived refresh-token storage should move to the generic core app-scoped secrets surface before production use.

## Verification

Focused checks:

```bash
python3 -m unittest discover -s tests -p 'test_gmail_app.py'
npm --prefix apps/gmail-app run build
python3 scripts/check_unused_imports.py
```
