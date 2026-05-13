---
name: checklist-ops
description: Create and manage workspace checklists through the Checklist app CLI and MCP surfaces.
---

# Checklist Operations

Use the app's official CLI or MCP surfaces:

- list checklists with action `list`
- create a chat-renderable checklist with MCP tool `checklist_tasklist`, action `create`, and `payload.sections[].tasks[]`
- create an agent-owned plan by setting `payload.mode` to `agent_plan` and using task fields such as `status`, `priority`, `description`, `dependencies`, `tools`, `blocked_reason`, `agent_ref`, `source_ref`, `agent_dialogs`, and `subtasks`
- read or reopen a checklist with action `read` or `recall` and `id`
- update a checklist with action `update`, `id`, and `payload.sections`
- add one task with action `add_task`, `id`, optional `section_id`, and `title`
- toggle one task with action `toggle_task`, `id`, `section_id`, and `task_id`
- update execution state with `set_task_status`, `id`, `section_id`, `task_id`, and `status`
- update nested execution state with `set_subtask_status`, `id`, `section_id`, `task_id`, `subtask_id`, and `status`
- inspect next open work with `next_actions`

The app's chat widget content kind is `checklist.design`. Successful create/read/update responses include `chat_render`; use that structured payload instead of writing checklist JSON in prose. Valid task statuses are `pending`, `in-progress`, `blocked`, `need-help`, `completed`, and `failed`. Users see a read-only work board; agents should update execution state through the official CLI or MCP surfaces.

Do not read or write another app's private data.
