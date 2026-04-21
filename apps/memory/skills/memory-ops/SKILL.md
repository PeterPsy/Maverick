---
name: memory-ops
description: "Use the Memory app to retrieve workspace context, save durable business facts, and link notes to files or app entities."
---

# Memory Ops

Use this skill when a user asks a workspace-specific question, asks about prior work, mentions business facts worth retaining, or asks about files, people, projects, decisions, or status.

## Retrieval First

Before answering a workspace-specific question, retrieve context:

```bash
memory context --query "<user question>" --limit 8
```

Use returned provenance to mention files or app entities only when they are relevant.

## Saving Memory

Save only stable, business-relevant information:

```bash
memory remember --title "<short title>" --body "<fact or note>" --type note
```

Prefer updating or linking existing nodes over creating duplicates.

## Linking Evidence

Attach files when they are relevant evidence:

```bash
memory attach-file --node <node_id> --file-id <file_id> --workspace-relative-path storage/uploaded/example.pdf --reason "<why it matters>"
```

Attach app entities when they clarify people, companies, deals, emails, or records:

```bash
memory attach-entity --node <node_id> --app crm --type person --id person_123 --title "Mario Rossi"
```

## Relationship Discipline

Create inferred relationships only with a reason and confidence:

```bash
memory link --source <node_id> --target <node_id> --kind supports --weight 0.8 --confidence 0.7 --reason "<why these are connected>"
```

Do not save speculative facts as confirmed memory. If uncertain, mark lower confidence or ask the user.

