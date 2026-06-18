# Mail

Mail is a source-available Maverick app for operating on email threads from inside a workspace. The repo source is contract-first and includes a React/Vite frontend, Python JSON backend, SQLite app-owned storage, CLI/MCP surfaces, reference entities, and a bundled `mail-ops` skill.

This implementation has real app surfaces with Gmail and Private Email providers. Gmail uses OAuth and the Gmail REST APIs. Private Email uses IMAP for sync/read state/attachment fetch and SMTP for sending, with mailbox credentials delivered only through Vault/Core Secrets.

## Surfaces

- Frontend: `frontend/dist`, built from `frontend/src`.
- Widgets: `mail-sidebar` for `shell.sidebar.primary` and `mail-sidebar-footer` for `shell.sidebar.footer`, mounted in `base-shell`.
- Backend: `backend/app_backend.py`, mounted through `/api/apps/mail/backend`.
- CLI: `mail`, with schema metadata in `cli/command_schemas.json`.
- MCP: thread search/read, draft creation/update/send preview, label modification, mark read, sync, view state, and reference tools with explicit schemas.
- Skill: `skills/mail-ops/SKILL.md`.
- Lifecycle hooks: install, migrate, and health check.
- Reference entities: `mail_connection`, `email_thread`, `email_message`, `mail_attachment`, and `mail_draft`.

The `mail-sidebar` widget owns mailbox filtering. It sends cumulative `mailbox_scopes`
such as `all:inbox` and `connection:<connection_id>:sent`; `threads.list` treats
those scopes as a union so sidebar checkbox selections add together instead of
replacing each other.

## Storage

The app owns `workspaces/<workspace_id>/data/mail/`.

Primary data lives in:

```text
data/mail/mail.sqlite
```

Schema version `8` stores connections, non-sensitive provider settings, OAuth flow metadata, redaction-safe credential references, folders, labels, threads, messages, bounded original HTML bodies, Gmail-sanitized HTML bodies, rendered HTML bodies, render policy metadata, MIME part metadata, inline asset metadata, attachment metadata, plain-text and optional HTML draft bodies, draft reply-to recipients, Storage-backed draft attachments, sync state, app-to-app entity links, and audit log entries. The install and migrate hooks are idempotent and create or upgrade the schema. The schema migration removes legacy local mock provider rows and leaves Gmail connections/cache intact.

Provider tokens, OAuth client secrets, and mailbox passwords must not be stored in this repository, frontend, logs, app events, SQLite raw fields, or Storage files. Providers resolve them through Vault/Core Secrets. The app database stores only connection metadata, non-sensitive IMAP/SMTP settings, `secret_ref`, `grant_id`, and non-sensitive token/credential metadata.

`connections.disconnect` is app-owned and local-first. It marks the connection `disconnected`, marks any app-owned OAuth credential metadata for that connection `disconnected`, records an audit log entry, and emits the Mail `connections` data event through backend/CLI/MCP wrappers. It intentionally preserves historic thread, message, attachment, draft, folder, label, and sync cache rows so workspace references and prior mail context remain readable. The app backend cannot directly revoke or delete Core Secrets values; Gmail refresh-token revocation must be performed through Core Secrets grant/secret administration surfaces. Disconnect responses and audit details state this limit explicitly.

Declared secret grants:

```text
gmail-oauth-client-id
gmail-oauth-client-secret
gmail-refresh-token
mailbox-password
```

`gmail-refresh-token` is written by the mounted backend as a per-resource app secret with `resource_type=mail_connection` and `resource_id=<connection_id>`. Gmail operations request OAuth client secrets as non-resource secrets and the refresh token as a resource-scoped selector. CLI and MCP tools use descriptor `secret_selectors`; for thread, draft, message, and attachment operations, the app resolves the owning Gmail connection before the core delivers the refresh token.

Private Email setup uses repeatable connection id `mail_connection_imap_team-loopino.ai` for `team@loopino.ai` by default. `connections.prepare_imap_smtp` creates the connection with status `needs_secret_grant` and stores only username, hosts, ports, TLS mode, folder metadata, and the redaction-safe `mail_connection` resource scope. The mailbox password is created or rotated in Vault, then granted to Mail as `mailbox-password` with `resource_type=mail_connection` and `resource_id=mail_connection_imap_team-loopino.ai`. `connections.test_imap_smtp` validates IMAP and SMTP with delivered secrets; `connections.activate_imap_smtp` marks the connection `connected` only after that test succeeds.

Gmail OAuth clients should register the app frontend callback path:

```text
/apps/mail/oauth/callback
```

The legacy root-shell path `/app/mail/oauth/callback` is accepted for existing flows, but new flows use `/apps/mail/oauth/callback` so the Mail frontend can complete the callback directly.

Gmail sync follows Gmail `nextPageToken` pagination up to the requested `max_threads` limit. `threads.sync` defaults to a 25-thread interactive batch so mounted backend, CLI, and widget calls return before the platform entrypoint timeout; callers that request larger batches should use `continue_cursor=true` and expect them to take proportionally longer. `threads.list` may still return a smaller page for UI readability and its lightweight cache refresh does not replace the persisted import cursor.

Private Email sync discovers IMAP folders, maps common folder names such as INBOX, Sent, Drafts, Trash, Junk, and Spam, stores per-folder UID cursors in `sync_state.cursor`, and performs bounded incremental fetches. Threading is local and based on `Message-ID`, `In-Reply-To`, `References`, with normalized subject fallback. SMTP sends multipart drafts using the configured mailbox identity and appends a best-effort sent copy through IMAP.

Outgoing draft APIs accept `body_text`, optional `body_html`, optional `reply_to` recipients, and optional `workspace_attachments` entries pointing at `storage/generated/...` or `storage/uploaded/...` files. Mail stores attachment metadata on the draft and returns it in the dry-run confirmation preview. Provider send previews build and validate the MIME message, including Storage attachment reads, before returning `requires_confirmation`; only `confirm=true` delivers the message externally. Gmail and SMTP sends build MIME multipart messages with the selected Storage files attached, and confirmed sends require the Gmail/IMAP connection secret selectors declared in the CLI/MCP descriptors.

Gmail thread fetches parse recursive MIME payloads and preserve both `text/plain` and bounded `text/html` bodies. MIME extraction stays in `backend/providers/gmail.py`; HTML rendering policy lives in `backend/email_rendering.py`, which owns body bounding, text fallback, preview generation, sanitizer rules, CSS policy, image placeholders, and safe HTML truncation for response limits. Messages persist `body_html_original_bounded` for server-side regeneration, `body_html_gmail_sanitized` for Gmail-oriented sanitizer output, `body_html_rendered` for the reader payload, and `render_policy_json` to make the renderer decision auditable. Read APIs keep `max_body_chars` as the text/plain limit and accept `max_body_html_chars` separately so the interactive reader can request full bounded HTML without forcing large plain-text previews. Response flags distinguish source, text, and HTML truncation with `body_source_truncated`, `body_text_truncated`, and `body_html_truncated`. The legacy `body_html_sanitized` field remains the bounded reader alias for current CLI/MCP/frontend consumers. The sanitizer allowlists common email tags, safe attributes, class/id selectors, and sanitized style blocks for responsive email layouts. Its CSS declaration allowlist follows Google's Gmail CSS support list, while media at-rules are limited to Gmail-supported `all`/`screen` width, device-width, orientation, and resolution queries. It strips scripts/forms/event handlers, blocks CSS resource URLs including escaped `url(...)` variants, removes unsupported at-rules such as imports/font faces/supports, and neutralizes image `src` and background-image resources so remote resources are not auto-loaded by default. Inline `cid:` image metadata is linked to the matching attachment record when Gmail exposes an attachment id; the reader fetches bounded inline image bytes on demand through `attachments.get` and injects them as data URLs inside the isolated iframe. Remote images and background images stay blocked by default with dimensioned placeholders, and the reader recalculates iframe height after image and layout changes. The reader iframe uses only a minimal document reset, preserves email-owned fonts, link colors, line heights, and table layout, and expands to the measured content width so wide email layouts scroll horizontally in the reader wrapper. The reader prefers rendered HTML when available, keeps a plain-text toggle, lets the user explicitly load remote images and background images for a message, folds Gmail quote blocks behind a native disclosure control, can refetch larger cached message bodies when a response-limit trim is shown, and separates reply and forward composer modes so replies stay threaded while forwards start a new draft.

## SDK Flow

```bash
maverick core cli run core.app-sdk.validate --app-root apps/mail --json
maverick app mail frontend build --json
maverick app mail cli list --json
maverick app mail mcp list --json
```

## Contract Notes

Mail is a source-available, forkable platform app. Its contract declares sandbox compatibility, app-owned SQLite storage, frontend/backend/CLI/MCP surfaces, sidebar widgets, Mail reference entities, standard Mail view-state actions, install/migrate/health hooks, and Vault/Core Secrets requirements for Gmail OAuth and IMAP/SMTP credentials.

## Verification

```bash
maverick core cli run core.app-sdk.validate --app-root apps/mail --json
maverick app mail frontend build --json
maverick app mail cli list --json
maverick app mail mcp list --json
python3 -m unittest discover -s apps/mail/tests -p 'test_*.py'
```

## Known Gaps

- Microsoft Graph is intentionally outside the MVP.
- Background sync and provider webhooks need generic platform scheduling/callback surfaces.
- Attachments are declared and resolvable as metadata. `mail_get_attachment` is metadata-only by default; callers must set `metadata_only=false` plus an explicit `max_bytes` to fetch bytes. `save_to_storage=true` stores bounded provider attachment bytes under `storage/generated/mail/attachments/` by default and returns a `workspace_relative_path` instead of embedding bytes in the response. `mail_save_attachments` saves matching attachments for an entire thread into a caller-selected generated Storage folder with filename/content-type/extension/size filters, content-hash dedupe before Storage persistence, `mode=create|overwrite|versioned`, and compact output refs containing `workspace_relative_path`, `size_bytes`, `sha256`, and source email metadata.
