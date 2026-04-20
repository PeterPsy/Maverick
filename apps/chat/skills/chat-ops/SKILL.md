---
name: chat-ops
description: Use the Chat app surfaces for workspace conversation threads and runtime turn operations.
---

# Chat Ops

Use the `chat` app surfaces for workspace conversation operations.

The chat app owns thread metadata and transcript UI. Runtime sessions, turns, provider selection, and runtime events are core-owned.

Use these surfaces:

- `threads.list` to inspect chat-owned thread metadata.
- Core runtime APIs to create sessions, send turns, read events, and stop turns.
- Core provider APIs to inspect or select the active provider.

Do not treat chat as the owner of provider credentials, runtime process lifecycle, memory, attachments, or other app data.
