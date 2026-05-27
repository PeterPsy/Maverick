# Mail

Mail is a workspace-local Maverick app for operating on email threads from inside a workspace. It follows the blueprint in `storage/generated/mail-maverick-app-blueprint.md`: contract-first app source, React/Vite frontend, Python JSON backend, SQLite app-owned storage, CLI/MCP surfaces, reference entities, and a bundled `mail-ops` skill.

This implementation is an MVP with real app surfaces and a Gmail provider. It builds the Gmail OAuth authorization flow, exchanges OAuth codes, stores per-connection refresh tokens through Core Secrets, and uses Gmail REST APIs for bounded sync, thread fetch, label changes, mark read/unread, send, and on-demand attachment fetch.

## Surfaces

- Frontend: `frontend/dist`, built from `frontend/src`.
- Widget: `mail-sidebar`, mounted in `base-shell` for `shell.sidebar.primary`.
- Backend: `backend/app_backend.py`, mounted through `/api/apps/mail/backend`.
- CLI: `mail`, with schema metadata in `cli/command_schemas.json`.
- MCP: thread search/read, draft creation/update/send preview, label modification, mark read, sync, view state, and reference tools with explicit schemas.
- Skill: `skills/mail-ops/SKILL.md`.
- Lifecycle hooks: install, migrate, and health check.
- Reference entities: `mail_connection`, `email_thread`, `email_message`, `mail_attachment`, and `mail_draft`.

## Storage

The app owns `workspaces/<workspace_id>/data/mail/`.

Primary data lives in:

```text
data/mail/mail.sqlite
```

Schema version `4` stores connections, OAuth flow metadata, secret references, folders, labels, threads, messages, attachment metadata, drafts, sync state, app-to-app entity links, and audit log entries. The install and migrate hooks are idempotent and create or upgrade the schema. The schema migration removes legacy local mock provider rows and leaves Gmail connections/cache intact.

Provider tokens and OAuth client secrets must not be stored in this repository, frontend, logs, app events, or Storage files. The Gmail adapter resolves them through Vault/Core Secrets. The app database stores only connection metadata, `secret_ref`, `grant_id`, and non-sensitive token metadata.

`connections.disconnect` is app-owned and local-first. It marks the connection `disconnected`, marks any app-owned OAuth credential metadata for that connection `disconnected`, records an audit log entry, and emits the Mail `connections` data event through backend/CLI/MCP wrappers. It intentionally preserves historic thread, message, attachment, draft, folder, label, and sync cache rows so workspace references and prior mail context remain readable. The app backend cannot directly revoke or delete Core Secrets values; Gmail refresh-token revocation must be performed through Core Secrets grant/secret administration surfaces. Disconnect responses and audit details state this limit explicitly.

Declared secret grants:

```text
gmail-oauth-client-id
gmail-oauth-client-secret
gmail-refresh-token
```

`gmail-refresh-token` is written by the mounted backend as a per-resource app secret with `resource_type=mail_connection` and `resource_id=<connection_id>`. Gmail operations request OAuth client secrets as non-resource secrets and the refresh token as a resource-scoped selector. CLI and MCP tools use descriptor `secret_selectors`; for thread, draft, message, and attachment operations, the app resolves the owning Gmail connection before the core delivers the refresh token.

Gmail OAuth clients should register the app frontend callback path:

```text
/apps/mail/oauth/callback
```

The legacy root-shell path `/app/mail/oauth/callback` is accepted for existing flows, but new flows use `/apps/mail/oauth/callback` so the Mail frontend can complete the callback directly.

Gmail sync follows Gmail `nextPageToken` pagination up to the requested `max_threads` limit. `threads.sync` defaults to 100 threads and accepts `max_threads` up to 2000; `threads.list` may still return a smaller page for UI readability and its lightweight cache refresh does not replace the persisted import cursor. Large imports should be run in batches with `continue_cursor=true` because each thread fetches full message metadata and may exceed interactive CLI/backend timeouts.

## Verification

```bash
maverick core cli run core.app-sdk.validate --app-id mail --json
maverick core cli run core.app-sdk.register-local --app-id mail --json
maverick core cli run core.app-sdk.install-local --app-id mail --json
maverick core cli run core.app-sdk.status --app-id mail --json
maverick app mail frontend build --json
maverick app mail cli list --json
maverick app mail mcp list --json
python3 -m unittest discover -s apps/mail/tests -p 'test_*.py'
```

When running from the Maverick installation root, use:

```bash
python3 -m unittest discover -s workspaces/default/apps/mail/tests -p 'test_*.py'
```

## Known Gaps

- Microsoft Graph and IMAP/SMTP are intentionally outside the MVP.
- Background sync and provider webhooks need generic platform scheduling/callback surfaces.
- Attachments are declared and resolvable as metadata. `mail_get_attachment` is metadata-only by default; callers must set `metadata_only=false` plus an explicit `max_bytes` to fetch bytes. `save_to_storage=true` stores bounded Gmail attachment bytes under `storage/generated/mail/attachments/` and returns a `workspace_relative_path` instead of embedding bytes in the response.
