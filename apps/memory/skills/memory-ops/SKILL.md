---
name: memory-ops
description: "Use the Memory app to retrieve workspace context, save durable business facts, delete Memory nodes, and link nodes to files or app entities."
---

# Memory Ops

Use this skill when a user asks a workspace-specific question, asks about prior work, mentions business facts worth retaining, or asks about files, people, projects, decisions, or status.

Keep user-facing progress updates short and operational. Prefer statements like "I am finding the exact Memory item before deleting it" over implementation details such as missing skill sections or internal source-code inspection.

## Retrieval First

Before answering a workspace-specific question, retrieve context:

```bash
maverick app memory cli run memory --action context --query "<user question>" --limit 8
```

Use returned provenance to mention files or app entities only when they are relevant.

When a result includes `storage_references`, use those Storage references for preview, export, or reference resolution. Memory stores knowledge and citations; Storage remains the file gateway.

Use a short retrieval path: small context, graph exploration only when needed,
then the evidence necessary for the answer. The common target is one to three
calls; original passages or audit reconstruction can require more.

`context` reserves up to two critical graph neighbors (`contradicts`,
`supersedes`) beyond the textual limit. Low-confidence connections remain
explicit; they are not proof. Follow `search_next_cursor` while
`retrieval_has_more` is true. `omitted_for_budget` and
`budget_omitted_node_ids` describe already retrieved items omitted by bytes:
batch their cards separately. `total_candidate_count` is null unless the first
page exhausts the candidates; do not infer an exact total from a limited page.
When `critical_has_more` is true, explore the selected nodes with
`kinds=["contradicts","supersedes"]` and follow the exploration cursor.
An empty evidence page can still have search continuation after invalid source
matches were rejected; follow its cursor rather than treating it as exhaustion.

Explore one to five known nodes without loading bodies or revisions:

```bash
maverick app memory mcp call memory_explore --node-ids '["node_..."]' --direction both --depth 1 --limit 10 --json
maverick app memory mcp call memory_explore --node-ids '["node_..."]' --kinds '["contradicts","depends_on","supersedes"]' --depth 2 --json
maverick app memory mcp call memory_get_nodes --node-ids '["node_a","node_b"]' --json
```

Keep the same seeds, direction, kinds, depth and scope when following
`next_cursor`. `stop_reason` distinguishes `limit`, `budget`, and `end`.
Cursors reject changed data instead of silently skipping results; restart the
page when stale. Parallel relationships have different `edge.id` values:
deduplicate by id, never by endpoint pair. Cards report indexed evidence state;
read the evidence section to observe source currency before relying on proof.
Track visited node IDs across follow-up explorations so cycles do not cause
repeated calls. Each page's `visited_node_ids` is its endpoint set.

For direct node lookup, inspection, or verification, use the Memory CLI instead of reading app data files:

```bash
maverick app memory cli run memory --action inspect --node-id <node_id> --detail evidence
```

`inspect` defaults to a card. Select `detail=evidence`, `content`, `sources`,
or `history` and follow the section's `next_cursor`. Batch reads are cards only.
`content=node|wiki` pages text; `detail=history` pages revision headers, and
`detail=content` with `revision_id` reads one historical body progressively.
`detail=evidence` with `claim_id` pages a claim's citations. `full` is an
explicit unbudgeted audit read, so avoid it during ordinary reasoning.
`max_bytes` bounds paged reads; if even one result cannot fit, increase the
budget or choose a card. Search defaults to cards; `detail=evidence` adds compact
proof and source matches. Queued compilation does not block existing source
access: evidence includes `available_source_chunks` to fetch immediately.
Use a card's `state_revision` to invalidate cached evidence, sources and compiled
state. The fact's `updated_at`/`revision` alone does not change for every evidence
update. Indexed card indicators do not supersede a live observation from evidence
inspection of the same state revision.

For source-level evidence, use Memory source primitives instead of reading `data/memory/` files:

```bash
maverick app memory mcp call memory_source_query --json --query "<source text or title>" --limit 10
maverick app memory mcp call memory_fetch_chunks --json --chunk-ids '["sch_..."]'
maverick app memory mcp call memory_inspect_source --json --source-document-id <source_document_id>
```

`memory_fetch_chunks` hydrates at most 20 chunks and verifies the content-store SHA before returning body text.

Ordinary source search returns current evidence linked to active knowledge. Use
`include_history=true` for superseded source versions and `include_excluded=true`
only when inspecting retained audit material. Source inspection returns bounded
version/chunk pages; follow `pagination.next_version_offset` and
`pagination.next_chunk_offset` with the same limits.

Check `compilation_state`, `source_state` and `verification` separately. A fresh
compilation does not establish that a fact is verified. Supporting citations and
contradictions are separate; relevant sources and uncertain paraphrases must not
be described as confirming proof. Search relevance is a ranking score. Use
stable `project_id` or `person_id` when knowledge must be restricted to that
scope; node metadata may also carry `aliases` and stable app references. The
same scope filters apply to context, search, wiki, sources and exploration.
`as_of=YYYY-MM-DD` selects validity at a date; default is today.
`include_expired=true` explicitly includes past/future validity intervals, and
`include_unscoped=true` includes general preferences beside scoped knowledge.
An as-of filter does not reconstruct overwritten facts: read revision/source
history for that. User confirmation (`confidence_basis`, `confirmation`),
source verification and agent-inferred relationships are independent.

When Memory returns queued ingest or compile work, inspect the app-owned job queue through Memory rather than editing SQLite:

```bash
maverick app memory cli run memory --action jobs_list --status ready --limit 20
maverick app memory mcp call memory_jobs --json --operation claim --job-types '["compile_node"]'
maverick app memory mcp call memory_jobs --json --operation run_until_idle --max-jobs 50
```

If an ingest, staleness, or compile request enqueues work and the current answer depends on it, drain a bounded batch with `run_until_idle` before answering. The platform tick progresses compile/lint work even with Memory closed; inspect `compilation_state` instead of assuming it has already completed. Other ingest and Storage reindex operations remain explicit.

Storage staleness can enqueue `requires_storage_reindex` jobs. Treat those jobs as action-required markers: run Storage `drive_index`, pass the returned Memory source to `memory_ingest_source` with `adapter_id=remote_storage_file`, and then acknowledge Storage indexing after Memory succeeds.

## Memory Views

When the user asks to filter or curate the Memory graph UI, use the Memory app view surface instead of only reading data:

```bash
maverick app memory cli run memory --action set_view_filter --query "Acme"
```

For a curated graph, pass Memory node references:

```bash
maverick app memory cli run memory --action set_custom_view --title "Acme context" --refs '[{"app_id":"memory","entity_type":"node","entity_id":"node_123"}]'
```

Use `clear_custom_view` to return the app to normal graph search mode.

Read operations never change that workspace view. A context response includes
`view.node_ids` and `view.snapshot_id` for a conversation-local reference view.
When opening Memory through shell navigation, send `context_node_ids` as the
JSON-encoded id array and `context_snapshot_id` as the retrieval id. Reopening
loads current cards, not a stored historical snapshot. Use revisions from the
original context to check changes. UI preview can show its referenced context
without writing shared view state; “Workspace view” returns to the shared view.

## Saving Memory

Save only stable, business-relevant information:

```bash
maverick app memory cli run memory --action remember --title "<short title>" --body "<fact or note>" --type note
```

Prefer updating or linking existing nodes over creating duplicates.

Repeated identical `remember` calls reuse the active content identity within
person/project/type/knowledge/validity scope. New unspecified confidence defaults
to 0.5 and zero remains zero; specify provenance and confidence basis rather than
treating the number as certainty.

For generated notes, imports, or other agent-owned Markdown evidence that is not a Storage or app-entity source, ingest it as an `inline_markdown` source so Memory stores a verifiable source version and chunk:

```bash
maverick app memory mcp call memory_ingest_source --json --adapter-id inline_markdown --source-key "<stable key>" --title "<source title>" --body-markdown "<markdown body>" --compile-after-ingest true
```

Use a stable `source_key` when the same generated source may be updated later. Re-ingesting identical content should not create duplicate source versions; changed content creates a new version and marks compiled Memory evidence stale.

Choose the ingest operation explicitly when changing existing knowledge:

- `attach_evidence` adds a source and retains curated fact text.
- `update_fact` updates the current assertion.
- `replace_fact` updates the assertion and records the replaced revision.

Pass `fact_body`, `fact_summary` and `fact_metadata` when the approved fact differs
from the original evidence. For an existing node, inspect first and pass
`expected_updated_at`; verify the returned body and revision after saving.
Generated document nodes follow their current source; curated notes retain their
text and show conflicts until explicitly reconciled. Preserve knowledge type,
person/project, validity, user confirmation and conversation provenance.

For local workspace Storage files, ingest through `storage_file` instead of reading Memory's database or content store directly:

```bash
maverick app memory mcp call memory_ingest_source --json --adapter-id storage_file --file-id <stable_file_id> --workspace-relative-path storage/generated/example.md --title "<source title>" --compile-after-ingest true
```

Memory accepts stable Storage file ids or workspace paths under `storage/uploaded/` or `storage/generated/`, and rejects mismatches when both point at different files. Memory resolves local file metadata, previewability, and bounded extracted content through Storage-owned `reference_resolve`, `file_info`, `preview_text`, and text `read_file` surfaces; previewable PDFs and Office files use Storage preview text, and non-extractable files are stored as `reference_snapshot` versions without chunks.

For records owned by another app, ingest through `app_entity` so Memory snapshots the official reference summary instead of reading the owner app's private data:

```bash
maverick app memory mcp call memory_ingest_source --json --adapter-id app_entity --owning-app-id crm --entity-type account --entity-id <account_id> --compile-after-ingest true
```

Memory uses the owning app's reference summarize/resolve surface and stores the app id, entity type, entity id, and deep link as the source locator.

## Ingesting Drive Sources

For Google Drive, Memory consumes only Storage references. Do not pass Google tokens, Drive bytes, or `workspace_relative_path` for remote files.

Use this flow after Storage `storage_drive_index` has selected one relevant Drive file:

```bash
maverick app memory mcp call memory_ingest_storage_source --json --memory-source '<storage_drive_index.memory_source>' --preview-text '<bounded preview_text>' --preview-truncated <true|false> --source-version <source_version> --compile-after-ingest true
```

Prefer the generic ingest front door for new workflows:

```bash
maverick app memory mcp call memory_ingest_source --json --adapter-id remote_storage_file --memory-source '<storage_drive_index.memory_source>' --preview-text '<bounded preview_text>' --preview-truncated <true|false> --source-version <source_version> --compile-after-ingest true
```

If the Storage file belongs on an existing Memory node, include `--node-id <node_id>`. If no node is supplied, Memory creates or reuses a file-backed node for the stable Storage file id.

After this succeeds, call Storage `storage_drive_mark_indexed` with the returned Memory ids so Drive sync can later produce staleness for files that actually reached Memory.

When Storage `drive_sync` returns `memory_staleness`, apply it through Memory:

```bash
maverick app memory mcp call memory_apply_storage_staleness --json --memory-staleness '<storage_drive_sync.memory_staleness item>'
```

The returned re-index suggestion points back to Storage `storage_drive_index`; Memory never scans Drive itself.

## Deleting Memory Items

When the user asks to remove a Memory item, first identify the exact active node. Use a narrow query based on the user's title, file name, person, project, or other clue:

```bash
maverick app memory cli run memory --action context --query "<target title or clue>" --limit 8
```

If there is exactly one clear match, soft-delete that Memory node with a reason:

```bash
maverick app memory cli run memory --action delete_node --node-id <node_id> --reason "<why it was removed>"
```

Then verify both that the node is deleted and that it no longer appears as active context:

```bash
maverick app memory cli run memory --action inspect --node-id <node_id>
maverick app memory cli run memory --action context --query "<target title or clue>" --limit 3
```

Deletion is a Memory soft delete: the node is marked `deleted`, active edges are removed, and the item is removed from Memory full-text retrieval. It does not delete the original file, email, CRM record, Drive document, or other external source referenced by the node.

`exclude_node` offers reversible exclusion from ordinary retrieval.
`remove_source` excludes a Memory source while retaining its audit content and
external original. Ordinary compilation and maintenance respect this removal;
an explicit remote reimport restores the source and queues reconciliation.
Excluded nodes can be restored or deleted with revision guards. Restore them
before correcting, verifying or merging. `merge_nodes` requires an explicitly chosen target, preserves
its fact text and transfers evidence and relationships. Inspect duplicate
suggestions and revisions before merging; use source and target revision guards.
The node inspector exposes these management actions, evidence passages, source
history and complete active relationships.

The platform background/recovery hooks perform bounded compile/lint maintenance
with a workspace-local process lock, job leases, deduplication and retries. The
UI does not drive queue progress. Full index integrity checking is an explicit
`memory_maintenance` request with `verify_index=true`, never a per-search scan.

If multiple plausible nodes match, ask the user to choose before deleting. If the user asks to delete the original linked source as well, switch to the owning app's official surface, such as Storage for files, and confirm destructive external deletion when needed.

## Linking Evidence

Attach files only when the Memory node needs a link back to a Storage item:

```bash
maverick app memory cli run memory --action attach_file --node-id <node_id> --file-id <file_id> --workspace-relative-path storage/uploaded/example.pdf --reason "<why it matters>"
```

If the file text should support citations or source-chunk retrieval, ingest it through `memory_ingest_source` with `adapter_id=storage_file` or `adapter_id=remote_storage_file` instead of relying on `attach_file`.

Attach app entities when they clarify people, companies, deals, emails, or records:

```bash
maverick app memory cli run memory --action attach_app_entity --node-id <node_id> --app records --type person --id person_123 --title "Mario Rossi"
```

## Relationship Discipline

Create inferred relationships only with a reason, confidence and `metadata.confidence_basis=agent_inferred`:

```bash
maverick app memory cli run memory --action link --source-node-id <node_id> --target-node-id <node_id> --kind supports --weight 0.8 --confidence 0.7 --reason "<why these are connected>"
```

Do not save speculative facts as confirmed memory. If uncertain, mark lower confidence or ask the user.
