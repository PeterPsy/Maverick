---
name: gallery-ops
description: "Use the Gallery app to inspect workspace uploaded files and generated artifacts through official Maverick app surfaces."
---

# Gallery Ops

Use Gallery when the user needs to inspect files under the active workspace storage roots.

Gallery derives its inventory from:

- `storage/uploaded/`
- `storage/generated/`

Prefer official Gallery MCP, CLI, or backend actions instead of walking these folders directly when operating inside Maverick.

Common actions:

- `catalog`: list uploaded and generated files with metadata.
- `read_file`: read a specific file by `role` and `relative_path` for preview or download workflows.
