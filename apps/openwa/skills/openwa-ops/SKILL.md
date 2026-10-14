---
name: openwa-ops
description: Inspect WhatsApp sessions and conversations, manage pairing, and send explicitly authorized messages through the native OpenWA app.
---

# OpenWA operations

Use the installed app's declared CLI or MCP operations. Inspect the current descriptors before assuming argument names or tool availability. The CLI command is `openwa`; its `action` selects an operation. Core admission rules still apply. If a runtime cannot invoke a workspace app, report that restriction; do not call the provider directly, import app source or read its private database to bypass it.

## Read and identify

Start with `status` and `sessions.list`. Use the returned session and chat identifiers exactly. Read `chats.list`, `contacts.list` and `messages.list` in bounded pages (at most 100). Never infer a telephone number from a WhatsApp LID or substitute a guessed chat ID. Webhook and template operations are read-only.

QR challenges and pairing codes are authentication material. Direct the user to **Manage session** in `/app/openwa`; do not paste challenges into chat, logs or generated files. Pairing and logout must refer to the intended session. Logout disconnects the account and requires explicit authorization.

Message lists omit inline media. Read a selected image with `messages.image`
(MCP `openwa_messages_image`) using its exact session, chat and returned `waMessageId`
as `message_id`. The response contains `mimetype`, `size_bytes` and `content_base64`;
inspect the image rather than printing its base64. The read accepts JPEG, PNG, WebP
and GIF up to 4 MiB (`max_bytes` may reduce that limit). It does not send or save a
file. Use Storage if a persistent copy is requested. A missing/expired image is an
explicit failure, not permission to read provider-private files.

For native CLI image bytes use `LOOPINO_RUNTIME_CLI_OUTPUT_PROFILE=full` on
that one invocation and consume the JSON into an image viewer or Storage;
the default text compaction can truncate base64. Never print the payload.

## Send messages

Require user authorization for the exact recipient and message. A request to install the app, connect an account or inspect a conversation does not authorize sending. Prepare the recipient and full text for review if either is missing from the authorization. Do not send a test message or perform bulk messaging on your own initiative.

Use `messages.send` or `messages.reply` with an `idempotency_key` of 12–100 letters, digits, hyphens or underscores. For a reply, `message_id` is the returned WhatsApp `waMessageId`, not the app database row ID. Keep the same key when retrying the same authorized message. A timeout can leave delivery uncertain: inspect the conversation before retrying, and never replace the key just to force a second send. Use a new key for a genuinely new message.

## Configuration and operations

Only platform administrators configure a gateway. Manage its API key and grants directly in Vault, then save the gateway URL in the app. Preserve the local provider credential when binding a remote gateway, and retain backend, CLI and MCP grant targets; never ask for the API key in chat or save it in source, notes, environment files or private storage. App secret delivery is ephemeral.

Connection and uncertain-send notices belong to Loopino's central inbox and the trusted current user. Do not build or use a separate app notification bell.

For an explicitly requested local-provider maintenance task, consult the shared app source's `OPERATIONS.md` in the Loopino design repository. Inspect the native `provider` CLI descriptor, then use its `status`, `start`, `restart` or `stop` action for the dedicated `loopino-openwa-default` supervisor. It is restricted to the trusted default-workspace platform administrator and requests no WhatsApp API key. Start enables persisted recovery; stop disables it. Host operator scripts live in `apps/openwa/provider/`. Do not restart other PM2 processes or Loopino's shared backend as part of ordinary OpenWA maintenance. Do not alter provider private data or authentication files.
