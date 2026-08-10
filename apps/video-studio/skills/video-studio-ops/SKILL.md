---
name: video-studio-ops
description: Use the `video-studio` Maverick app through its declared CLI and MCP surfaces.
---

# Video Studio Operations

Use only the app's official CLI or MCP surfaces. Never read another app's
private data, fabricate a host path, put a remote URL into Project IR, or invoke
render/ingest behavior that this version does not implement.

Start with the CLI `video-studio` action `capabilities` or the
`video_studio_foundation` MCP tool. The implemented domain capability IDs are
`project-ir.v1`, `revision-engine.v1`, `typed-editing.v1`, and
`native-interchange.v1`.

The CLI command accepts the declared actions in `cli/command_schemas.json`.
MCP exposes explicit tools for project create/list/get/rename/duplicate,
archive/restore, revision get/compare, native export/import, typed operation
batch apply, undo, and redo. Discover their exact schemas from
`mcp/tool_schemas.json`; do not invent arguments.

For every edit, first read the project and use its current `head_revision_id`
as `base_revision_id`. Generate one stable `operation_batch_id`, include the
trusted workspace, actor, preconditions, ordered typed operations, and autosave
metadata, then retain the same complete request for retries. A stale head is a
real concurrency conflict: read the new revision and ask the user how to
reconcile; never silently rewrite the base.

Treat native export as a validated JSON domain envelope, not a rendered media
file or app backup. Import is workspace-confined and digest-checked. Use Storage
surfaces separately if a user explicitly needs a user-facing saved document.

Undo/redo are persistent revision-head moves and also require typed batch
envelopes. They survive app process restart. Archived projects are read-only
until restored.

Do not claim ingest, transcoding, media search, rendering, FFmpeg execution,
Remotion preview, agent proposals, or frontend editing. Those capabilities are
outside this app version.
