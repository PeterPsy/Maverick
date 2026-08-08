---
name: video-studio-ops
description: Use the `video-studio` Maverick app through its declared CLI and MCP surfaces.
---

# Video Studio Operations

Use the app's official CLI or MCP surfaces. Do not read or write another app's
private data and never construct a host path for Video Studio media.

This foundation checkpoint exposes the `video_studio_foundation` MCP tool and
the `video-studio` CLI command. Both accept an optional `action` of `status`,
`schema`, `health`, or `capabilities`. The MCP surface also exposes the common
`video_studio_reference_manifest`, which correctly reports no reference entity
types until those domain records are implemented.

Use `capabilities` before assuming that an editing, media-analysis, proposal,
or rendering surface exists. An empty `domain_capabilities` list means those
later product slices are not yet available; do not present scaffold behavior
as completed video editing.
