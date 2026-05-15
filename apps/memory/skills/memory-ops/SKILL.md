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
