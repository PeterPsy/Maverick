---
name: docs-studio-ops
description: Use the `docs-studio` Maverick app through its declared CLI and MCP surfaces.
---

# Docs Studio Operations

Use the app's official CLI or MCP surfaces for targeted documentation lookup, status, state reads, and reference discovery. The mounted frontend is the primary editing experience.

Do not read or write another app's private data.

Prefer targeted documentation calls before broad core developer-context reads:

```bash
maverick app docs-studio cli run docs-studio --subcommand manifest --section_id core-architecture
maverick app docs-studio cli run docs-studio --subcommand search --query "provider credentials" --limit 5
maverick app docs-studio cli run docs-studio --subcommand read --page_id provider-credentials --max_chars 12000
```

MCP equivalents:

- `docs_studio_docs_manifest`
- `docs_studio_docs_search`
- `docs_studio_docs_read`

Use `docs_studio_state` only when the caller really needs the composed UI state.
