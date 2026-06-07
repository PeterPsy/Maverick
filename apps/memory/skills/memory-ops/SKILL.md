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

For direct node lookup, inspection, or verification, use the Memory CLI instead of reading app data files:

```bash
maverick app memory cli run memory --action inspect --node-id <node_id>
```

For source-level evidence, use Memory source primitives instead of reading `data/memory/` files:

```bash
maverick app memory mcp call memory_source_query --json --query "<source text or title>" --limit 10
maverick app memory mcp call memory_fetch_chunks --json --chunk-ids '["sch_..."]'
maverick app memory mcp call memory_inspect_source --json --source-document-id <source_document_id>
```

`memory_fetch_chunks` hydrates at most 20 chunks and verifies the content-store SHA before returning body text.

When Memory returns queued ingest or compile work, inspect the app-owned job queue through Memory rather than editing SQLite:

```bash
maverick app memory cli run memory --action jobs_list --status ready --limit 20
maverick app memory mcp call memory_jobs --json --operation claim --job-types '["compile_node"]'
maverick app memory mcp call memory_jobs --json --operation run_until_idle --max-jobs 50
```

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

## Saving Memory

Save only stable, business-relevant information:

```bash
maverick app memory cli run memory --action remember --title "<short title>" --body "<fact or note>" --type note
```

Prefer updating or linking existing nodes over creating duplicates.

For generated notes, imports, or other agent-owned Markdown evidence that is not a Storage or app-entity source, ingest it as an `inline_markdown` source so Memory stores a verifiable source version and chunk:

```bash
maverick app memory mcp call memory_ingest_source --json --adapter-id inline_markdown --source-key "<stable key>" --title "<source title>" --body-markdown "<markdown body>" --compile-after-ingest true
```

Use a stable `source_key` when the same generated source may be updated later. Re-ingesting identical content should not create duplicate source versions; changed content creates a new version and marks compiled Memory evidence stale.

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

If multiple plausible nodes match, ask the user to choose before deleting. If the user asks to delete the original linked source as well, switch to the owning app's official surface, such as Storage for files, and confirm destructive external deletion when needed.

## Linking Evidence

Attach files when they are relevant evidence:

```bash
maverick app memory cli run memory --action attach_file --node-id <node_id> --file-id <file_id> --workspace-relative-path storage/uploaded/example.pdf --reason "<why it matters>"
```

Attach app entities when they clarify people, companies, deals, emails, or records:

```bash
maverick app memory cli run memory --action attach_app_entity --node-id <node_id> --app records --type person --id person_123 --title "Mario Rossi"
```

## Relationship Discipline

Create inferred relationships only with a reason and confidence:

```bash
maverick app memory cli run memory --action link --source-node-id <node_id> --target-node-id <node_id> --kind supports --weight 0.8 --confidence 0.7 --reason "<why these are connected>"
```

Do not save speculative facts as confirmed memory. If uncertain, mark lower confidence or ask the user.
