---
name: chat-ops
description: Use Chat UI surfaces with core-owned workspace conversation threads and runtime turn operations.
---

# Chat Ops

Use Chat UI surfaces for workspace conversation operations.

The core owns thread metadata, runtime sessions, turns, provider selection, runtime events, process lifecycle, and complete thread deletion. The chat app owns UI state and chat projects only.

Use these surfaces:

- Core runtime APIs to list/create/update/delete threads, create sessions, send turns, read events, and stop turns.
- Core provider APIs to inspect or select the active provider.
- Chat app surfaces only for project and view-filter state.

Do not treat chat as the owner of provider credentials, runtime process lifecycle, runtime memory, runtime logs, or thread history.
