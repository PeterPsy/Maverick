---
name: checklist-ops
description: Create and manage workspace checklists through the Checklist app CLI and MCP surfaces.
---

# Checklist Operations

Use the app's official CLI or MCP surfaces:

- list checklists with action `list`
- create a chat-renderable checklist with MCP tool `checklist_tasklist`, action `create`, and `payload.sections[].tasks[]`
- read or reopen a checklist with action `read` or `recall` and `id`
- update a checklist with action `update`, `id`, and `payload.sections`
- add one task with action `add_task`, `id`, optional `section_id`, and `title`
- toggle one task with action `toggle_task`, `id`, `section_id`, and `task_id`

The app's chat widget content kind is `checklist.design`. Successful create/read/update responses include `chat_render`; use that structured payload instead of writing checklist JSON in prose.

Do not read or write another app's private data.
