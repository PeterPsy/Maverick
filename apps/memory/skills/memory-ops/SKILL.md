---
name: memory-ops
description: "Use the Memory app to retrieve workspace context, save durable business facts, and link nodes to files or app entities."
---

# Memory Ops

Use this skill when a user asks a workspace-specific question, asks about prior work, mentions business facts worth retaining, or asks about files, people, projects, decisions, or status.

## Retrieval First

Before answering a workspace-specific question, retrieve context:

```bash
maverick app memory cli run memory --action context --query "<user question>" --limit 8
```

Use returned provenance to mention files or app entities only when they are relevant.

When a result includes `storage_references`, use those Storage references for preview, export, or reference resolution. Memory stores knowledge and citations; Storage remains the file gateway.

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

## Ingesting Drive Sources

For Google Drive, Memory consumes only Storage references. Do not pass Google tokens, Drive bytes, or `workspace_relative_path` for remote files.

Use this flow after Storage `storage_drive_index` has selected one relevant Drive file:

```bash
maverick app memory mcp call memory_ingest_storage_source --json --memory-source '<storage_drive_index.memory_source>' --preview-text '<bounded preview_text>' --preview-truncated <true|false> --source-version <source_version> --compile-after-ingest true
```

If the Storage file belongs on an existing Memory node, include `--node-id <node_id>`. If no node is supplied, Memory creates or reuses a file-backed node for the stable Storage file id.

After this succeeds, call Storage `storage_drive_mark_indexed` with the returned Memory ids so Drive sync can later produce staleness for files that actually reached Memory.

When Storage `drive_sync` returns `memory_staleness`, apply it through Memory:

```bash
maverick app memory mcp call memory_apply_storage_staleness --json --memory-staleness '<storage_drive_sync.memory_staleness item>'
```

The returned re-index suggestion points back to Storage `storage_drive_index`; Memory never scans Drive itself.

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
