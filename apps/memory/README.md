# Memory

Workspace visual knowledge map for durable agent and user memory.

Memory keeps the human product surface graph-first. Under the hood it compiles workspace sources into an agent-optimized internal LLM Wiki made of compiled pages, atomic claims, citations, source links, compile runs, and lint findings. The compiled wiki is not a separate user-facing app or route; it is evidence visible from node inspection and from agent-facing context surfaces.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- Memory ships app-owned CLI and MCP descriptor sidecars at `cli/command_schemas.json` and `mcp/tool_schemas.json`. These populate `maverick app memory cli inspect memory --json` and `maverick app memory mcp inspect <tool> --json` with operation-specific descriptions and JSON schemas for current agent-facing operations.
- The frontend is a React/Vite graph workspace with a dark token-aligned canvas, live refresh, canvas graph navigation, readable node inspection, compiled wiki evidence, references, relationship browsing, and a create-node modal.
- The base-shell sidebar widgets provide Memory search, node navigation, a footer context-preview action that opens the app modal, and an icon-only create action that opens the app create modal.
- The contract declares the bundled `memory-ops` skill, persisted view-state actions, `memory_compile`, `memory_lint`, `memory_wiki_query`, `memory_ingest_storage_source`, `memory_apply_storage_staleness`, and the `node` reference entity.
- App-owned storage lives under `data/memory/` for the SQLite graph, internal wiki tables, and attached artifacts.
- Memory is one of the repository reference apps for complete stateful contract coverage.

## Runtime Behavior

- Frontend backend calls derive the mounted app id from `/apps/<mount_app_id>/...`, so workspace-local forks use their local backend mount instead of a hardcoded `memory` route.
- Frontend backend calls normalize HTTP and app-level errors and support abort/timeout handling for stale requests.
- The graph canvas uses pointer gestures across desktop and mobile: drag empty space to pan, drag a node to move/select it, pinch to zoom, and wheel to zoom on pointer devices.
- The graph action returns a lightweight node/edge summary for canvas and sidebar rendering. Full external references and edge details are loaded through `inspect`.
- `compile` deterministically builds the internal wiki page for a node from the current node text, external references, and relationships. It records source/version rows, claims, a compile run, and current lint findings without calling an LLM yet. Citations are recorded only when Memory has credible claim-level evidence such as a chunk, locator, range, quote, or extracted reference; remote Storage citations include the Storage source version used for ingestion.
- Storage file references are split into `local_storage_file` and `remote_storage_file`. Local files may use `workspace_relative_path` under `storage/uploaded/` or `storage/generated/`. Remote files, including Google Drive files, must reference `owning_app_id=storage`, `entity_type=file`, a stable `file_...` Storage entity id, and remote metadata such as `provider`, `connection_id`, `drive_file_id`, `source_version`, and `display_path`.
- Memory never treats Google Drive as a workspace path and never receives Google tokens. Remote source ingestion asks Storage for bounded preview text using the stable Storage file reference; Storage remains responsible for Drive OAuth, export/download policy, provider capabilities, and remote bytes.
- `inspect` returns the compiled page, claims, citations, source links, Storage references, and lint findings for the selected node. `context` includes the compact compiled pack when one exists.
- `search` covers nodes plus compiled wiki page and claim text; `wiki_query` returns wiki-page and claim matches directly for agents. `context`, `search`, and `wiki_query` include normalized `storage_references` with stable Storage file ids, Drive ids, source versions, deep links, and preview/export request arguments when available.
- `lint` refreshes app-owned findings such as missing citations, contradictions, orphan nodes, empty content, and stale compiled pages. When Storage metadata reports remote source staleness or a non-healthy sync state, Memory marks the compiled wiki stale so the source can be re-indexed through Storage.
- SQLite connections enable foreign keys, WAL, `busy_timeout`, and explicit write transactions. Schema creation is skipped after the current schema version has been installed.
- Numeric request fields reject non-finite values, and SQLite constraint failures are returned as validation errors instead of crashing entrypoints.
- Context retrieval does not write audit telemetry by default; `record_access_event` is opt-in. Inspect, context, wiki query, and lint surfaces may still materialize stale freshness and lint markers when they detect changed node inputs or source file bytes.
- Sidebar search text is widget-local. Persisted view-state changes are reserved for explicit view actions such as `set_custom_view`, `set_view_filter`, and `clear_custom_view`.

## Agent-First Drive To Memory Contract

Memory is the knowledge and retrieval layer for Storage-hosted Drive content. It consumes stable Storage references; it does not become a Drive client and does not receive Google secrets.

The operating contract is:

- Storage discovers Drive files, reads/export/previews their content, owns Drive sync, and produces `memory_source` payloads from `drive_index`.
- Memory accepts `local_storage_file` for workspace Storage paths and `remote_storage_file` for Drive files. Remote references must use `owning_app_id=storage`, `entity_type=file`, stable `entity_id=file_...`, and metadata containing `provider=google_drive`, `connection_id`, `drive_file_id`, and `source_version` when available.
- Memory rejects `workspace_relative_path` for remote Drive providers and must never persist Google tokens, refresh tokens, OAuth codes, or Drive filesystem paths.
- During compile, Memory may request bounded preview text from Storage through official Storage surfaces using the stable Storage file reference. Storage remains responsible for Drive permissions, export limits, temporary cache policy, and bytes.
- Memory citations and source links must keep enough Storage metadata for an agent to return to Storage for preview, export, reference resolution, or deep-link display. Citation payloads expose `source_version` and, when backed by Storage, a nested `storage_reference` usable with `storage_drive_preview`, `storage_drive_export`, or `storage_reference_resolve`.
- Storage-originated staleness is applied through `apply_storage_staleness` / `memory_apply_storage_staleness`, which consumes `drive_sync.memory_staleness`, marks every linked Storage ref with stale metadata and sync state, marks impacted compiled wiki pages and claims stale, and returns impacted nodes plus a bounded `storage_drive_index` re-index suggestion. Memory does not scan Drive. Rich Storage payloads may include `connection_id`, `drive_file_id`, current `source_version`, and `indexed_source_version`; Memory preserves those fields in the ref staleness metadata and re-index suggestion.

The target autonomous workflow is:

1. The agent asks Memory first through `memory_context`, `memory_search`, or `memory_wiki_query`.
2. If the answer needs fresh Drive evidence, the agent searches or navigates Drive through Storage.
3. The agent calls `storage_drive_index` for selected files.
4. The Memory `ingest_storage_source` action consumes the returned `memory_source`, optional `node_id`, optional `title`, optional bounded `preview_text`, required `source_version`, and `compile_after_ingest`. If `node_id` is omitted, Memory creates or reuses a file-backed node for the stable Storage `file_...` identity. If `node_id` is present, Memory attaches or updates that Storage source on the target node without moving the same Drive file away from other nodes that already cite it.
5. After Memory ingest succeeds, the agent acknowledges the Storage side with `storage_drive_mark_indexed`, passing the same `stable_storage_file_id`, `source_version`, and when available `memory_node_id`, `memory_external_ref_id`, and `memory_source_version_id`. This prevents Storage from advertising files as indexed before they are actually in Memory and gives later sync diagnostics a trace back to the Memory ingest.
6. Retrieval returns compiled content, claims, citations, source versions, and Storage reference metadata.
7. When the document itself needs to be shown, the agent goes back to Storage with the citation/reference and calls the appropriate preview, export, or reference surface.

Operationally, agents should keep the loop selective:

- Stop at Memory when `memory_context`, `memory_search`, or `memory_wiki_query` returns fresh enough evidence.
- Search or navigate Drive only when Memory is missing, stale, or the user explicitly needs fresh Drive material; select a bounded candidate set rather than indexing a folder or all Drive.
- Hand off `storage_drive_index.memory_source`, `preview_text`, `preview_truncated`, and `source_version` directly to `memory_ingest_storage_source` with `compile_after_ingest=true` when immediate reasoning is needed, then call `storage_drive_mark_indexed` after Memory succeeds.
- Use `storage_references[].preview_request`, `storage_references[].export_request`, `citations[].storage_reference`, or `deep_link` from Memory retrieval to show the document through Storage. Memory never serves raw Drive bytes.

`ingest_storage_source` is idempotent by stable Storage file id when no target node is provided, and idempotent by `(node_id, stable_storage_file_id)` when a target node is provided. This lets one Drive file support multiple Memory nodes while avoiding duplicate refs on the same node. It requires a Storage `source_version` so source versions and citations remain stable. A successful ingest clears prior Storage stale metadata for that file reference. When `compile_after_ingest=true`, Memory compiles immediately into sources, source versions, claims, citations, and a compiled wiki page. If Storage preview/export is unavailable and no bounded `preview_text` was supplied, compilation fails without creating a fresh source version or fresh wiki page.

`apply_storage_staleness` accepts the Storage sync payload shape, for example `owning_app_id=storage`, `entity_type=file`, `entity_id=file_...`, and `reason=google_drive_change`, plus optional Drive locator and version fields. It updates every matching `external_refs` row for that Storage file identity and leaves re-indexing explicit: the agent should call Storage `drive_index`, then Memory `ingest_storage_source` with `compile_after_ingest=true`.

## SDK Flow

Validate the installation-level Memory source directly:

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id memory --app-root apps/memory --workspace default --json
```

Workspace-local registration and installation commands target a workspace-owned copy under `workspaces/default/apps/memory`:

```bash
./scripts/maverick core cli run core.app-sdk.register-local --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id memory --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id memory --workspace default --json
```
