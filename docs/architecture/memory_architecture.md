# Memory Architecture

Date: 2026-06-19

## Purpose

Define the target architecture for the built-in Memory app.

Memory is a visual knowledge map backed by an internal compiled wiki. The app must not become a second `llmwiki` app and the core must not own memory semantics.

## Product Shape

Memory's user-facing surface is a graph of durable workspace knowledge:

- nodes represent human-meaningful entities such as notes, facts, files, app-entity references, people, companies, projects, topics, decisions, and questions
- edges represent typed relationships such as support, contradiction, derivation, dependency, ownership, and topic membership
- the node inspector is the place where users see evidence, relationships, compiled summaries, claims, citations, freshness, and lint findings

The compiled wiki layer is internal app-owned data. It is inspectable evidence, not a separate wiki navigation product.

## Storage Boundary

All Memory data lives under:

```text
workspaces/<workspace_id>/data/memory/
```

The app may use SQLite and app-owned artifacts inside that root. The core hosts Memory through app contracts, CLI, MCP, backend, frontend, hooks, and data events, but it must not read or enforce Memory's SQLite schema.

Memory's verified content store lives under:

```text
workspaces/<workspace_id>/data/memory/content/
  sources/<sha-prefix>/<body_sha256>.md
  chunks/<sha-prefix>/<chunk_sha256>.md
```

Only relative content paths may be persisted in Memory data. The app must reject absolute paths and path traversal, resolve content paths below `data/memory/content/`, and verify the stored body SHA before using source or chunk text for compile and retrieval. Content files are immutable once written; metadata front matter is non-authoritative and must not affect the body hash.

## Compiled Wiki Model

The internal wiki model is app-owned and should include:

- `source_documents`: logical source identities from inline markdown, Storage files, remote Storage references, app entities, URLs, or future adapters
- `sources`: stable references to Storage files, generated artifacts, chat/app entities, URLs, or other workspace-owned material
- `source_versions`: observed source versions with hash kind, extraction status, content-store body path/hash when text is available, observed source metadata, and extracted-reference pointers; `extracted_text` is retained only as a legacy migration fallback
- `source_chunks`: verified source body slices with chunk hash, range, locator, and content-store path
- `node_source_links`: explicit node-to-source relationships
- `wiki_pages`: compiled markdown for a node or topic
- `claims`: atomic statements derived from node content and sources
- `citations`: claim-to-source evidence links
- `compile_runs`: compilation provenance and input hashes
- `lint_findings`: current quality findings such as missing citation, contradiction, stale page, orphan node, or empty content

Raw sources stay authoritative. Compiled pages and claims are derived artifacts that can be regenerated.

Deterministic compilation must consider both external references that need source synchronization and app-owned source links already attached to a node. It must not create placeholder citations just because a source is linked to a node. Source links show provenance candidates; citations require credible evidence such as a chunk, locator, range, quote, or extracted-reference pointer that supports the specific claim. Until that exists, claims remain uncited and lint should report `missing_citation`.

The canonical source-version hash kinds are `canonical_body`, `file_bytes`, `remote_storage_preview`, and `reference_snapshot`. When source extraction is unavailable, Memory may store a source version with `metadata.hash_kind = reference_snapshot` to capture the observed reference fields. That snapshot is not a content hash. For workspace files, Memory should use observed file-byte hashes when the file can be resolved from the workspace root. For remote Storage files, Memory uses `remote_storage_preview` only when Storage returns bounded preview text that Memory can store as extracted source body; otherwise the version is a `reference_snapshot`. Additive migrations must preserve explicit legacy `hash_kind` values and infer `remote_storage_preview` for legacy remote Storage versions that already contain extracted preview text.

Chunk-level citations are the target evidence form. A fully verifiable citation should carry at least `claim_id`, `source_version_id`, `source_chunk_id`, locator or character range, and a quote or quote hash. Character ranges must point at the stored source chunk body; whitespace-normalized quote matches may map back to original chunk offsets, but unmatched quotes must not receive fabricated ranges. Compile runs should record the source version ids and source chunk ids considered, plus the cited subset that actually supported claims. If Memory cannot bind a claim to a credible chunk, range, locator, or quote, it must leave the claim uncited instead of implying support from an attached source alone.

The deterministic compiler may bind citations with exact quote matching or conservative lexical matching over adjacent source sentences, so paraphrased node claims and multi-sentence evidence can still cite verified chunks. This matcher must remain fail-closed: partial overlap is not enough unless it clears explicit coverage and precision thresholds against the claim terms.

## Source Ingestion Model

Memory ingestion is app-owned and separate from compile:

1. normalize an adapter payload into a logical source document
2. create or reuse the matching source document
3. create a source version from canonical body text, observed file bytes, remote preview text, or a reference snapshot
4. write available canonical bodies and chunks to the content store
5. create source chunks with stable hashes and locators
6. enqueue or explicitly run compile and lint work

The first implemented generic adapters stay narrow:

- `inline_markdown` for tests, imports, and generated notes
- `storage_file` for workspace Storage files by stable Storage file id or workspace-relative Storage path, using official Storage `reference_resolve`, `file_info`, `preview_text`, and bounded text `read_file` surfaces before Memory stores verified source/chunk content; previewable PDFs and Office documents use Storage preview text, while files without extractable text are recorded as `reference_snapshot` versions without chunks
- `remote_storage_file` for Storage-owned Drive indexing payloads by stable Storage file id, provider metadata, source version, and bounded preview text
- `app_entity` for redaction-safe snapshots from another enabled app's official reference summarize/resolve surfaces, without reading that app's private database

Drive ingestion is accepted through the generic `memory_ingest_source` surface with `adapter_id=remote_storage_file`, while the transitional `memory_ingest_storage_source` surface remains as a compatibility alias over the same validation and materialization path. The ingest step must materialize the source document, observed source version, and source chunks before compile so Drive content is queryable as verified source evidence even when immediate compile is not requested. Drive remains Storage-owned and Memory never reads Drive directly.

`app_entity` snapshots are reference snapshots, not raw app database exports. They may provide citeable extracted-reference chunks when the owning app returns a redaction-safe summary, but Memory must keep the owning app id, entity type, entity id, and deep link as the source locator.

Storage remains the owner of local files, Drive OAuth, Drive bytes, preview/export policy, and stable Storage file ids. Memory consumes Storage references and bounded previews through official Storage surfaces and must not persist Google tokens, refresh tokens, OAuth codes, client secrets, or absolute provider paths. The current local implementation may use the platform-hosted CLI/MCP wrapper as the transport for those official surfaces until a direct app-to-app SDK is available; it must still treat the provider app's private files and databases as off limits. The legacy `memory_attach_file` path remains link-oriented; citation-ready local and remote content should enter through `memory_ingest_source`, and any legacy stored workspace path must be revalidated before Memory hashes local bytes.

## Runtime Surfaces

Memory exposes agent-facing surfaces through the app contract:

- `memory_context` returns bounded `agent_compact` `memory_node` context packs for provider context. Items preserve node identity, title, type, summary, bounded `body_text` snippets, `body_text_char_count`, relevance, match sources, compact provenance, compact Storage references, compact compiled wiki summaries/citations/freshness, and expand instructions. It must not duplicate full `body_text` under nested node envelopes or return full compiled `body_markdown`; callers needing full detail should expand by node or source chunk id.
- `memory_inspect_node` returns node details plus compiled page, claims, citations, sources, and lint findings
- `memory_search` searches graph nodes plus compiled page and claim text and returns the richer normalized `memory_node` retrieval envelope for search workflows. Agents should prefer `memory_context` for default prompt context and use `memory_inspect_node` or `memory_fetch_chunks` to expand specific results.
- `memory_compile` compiles one node into the internal wiki layer and emits a redaction-safe `memory_compile_completed` event with compile/run counts, not source text
- `memory_lint` refreshes quality findings and emits a redaction-safe `memory_lint_refreshed` event with node and severity counts
- `memory_ingest_source` ingests generic app-owned sources. The implemented adapters are `inline_markdown` for generated Markdown evidence, `storage_file` for workspace Storage files under `storage/uploaded/` or `storage/generated/`, `remote_storage_file` for Storage-owned Drive indexing payloads, and `app_entity` snapshots through official app reference surfaces; Storage-backed adapters ask Storage for file metadata, previewability, bounded preview text, and only then bounded UTF-8 text bytes as fallback before writing Memory-owned verified source bodies and chunks, or a `reference_snapshot` when extraction is unavailable
- `memory_wiki_query` searches compiled wiki pages and claims directly
- `memory_source_query` searches verified source chunks through Memory's app-owned source chunk FTS and returns normalized source-chunk results
- `memory_fetch_chunks` hydrates up to 20 source chunks from the content store with SHA verification; chunk retrieval surfaces should expose normalized chunk identity, freshness, locator, and citations when available
- `memory_inspect_source` inspects one source document with normalized freshness, versions, chunks, linked nodes, citations, and recent ingest jobs linked through indexed job provenance fields
- `memory_jobs` manages Memory's app-owned ingest job queue with dedupe, claim leases, expired-lease recovery, retry backoff, cancellation, inspection, `run_next` execution, and bounded `run_until_idle` queue draining for the first app-owned job types. The first phase stays independent of the core scheduler: agents and operators explicitly drain ready work when they need queued ingest, compile, or staleness jobs reflected immediately. `run_next` updates the job's indexed node/source provenance from the execution result before completing the lease, so source-ingest jobs remain auditable when they create a new observed source version. Storage staleness uses an explicit `requires_storage_reindex` job marker so Memory can report the required Storage `drive_index` step without attempting to re-ingest stale Drive content before Storage provides a fresh `memory_source`.

Future ingestion and execution surfaces should expand source primitives without changing core ownership:

- richer Storage preview/extraction paths where Storage remains the gateway
- richer chunk indexing, including later optional embeddings as app-owned indices

The first compiler may be deterministic and use existing node text, references, source links, and relationships. LLM-assisted compilation can be added later, but it must preserve citations, input provenance, lint results, and source version identity. Source chunk retrieval should expose freshness relative to the latest observed source version so older-version chunks remain auditable without being presented as current evidence.

## UI Rule

Do not add a separate Wiki tab or app. The graph stays primary. Full compiled wiki content appears in the node inspector; agent-facing context payloads expose compact compiled summaries, citations, freshness, and expansion pointers.
