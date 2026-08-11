# Revision engine transaction contract

The revision engine owns one SQLite database per workspace binding. Backend,
CLI, and MCP use the same `ProjectService`; transports do not mutate Project IR
directly.

## Identity and canonical revisions

Every accepted Project IR document is serialized with sorted object keys,
UTF-8, no insignificant whitespace, and no floats. Its SHA-256 digest is the
content address and produces `revision-<digest>`. Revision rows are immutable.
Revisiting identical historical content selects the existing content-addressed
revision rather than creating a mutable copy.
Schema v3 enforces immutability with SQLite `BEFORE UPDATE` and `BEFORE DELETE`
triggers; it also rejects branch, projection, navigation, batch, autosave, and
outbox revision references whose revision belongs to another project.

The `main` branch stores one current head. `project_projections` is a derived,
transactionally updated read projection containing name, duration, asset count,
and track count. The document remains authoritative.

## Operation batch protocol

Every editing/history batch contains exactly:

```text
workspace_id, project_id, base_revision_id, operation_batch_id,
preconditions, actor, operations, autosave, metadata
```

The envelope is bounded canonical JSON and passes the same active/external
content security scan. Operations are ordered typed domain commands, not JSON
Patch. A batch ID is unique within a project. An identical retry returns the
stored deterministic result; reuse with different canonical content returns
`operation_batch_id_conflict`.

The trusted workspace must match the envelope and Project IR provenance. Each
database is atomically bound to its first trusted workspace context and refuses
reuse under another workspace. On backend, CLI, and MCP, the batch actor field
is overwritten from the host-owned `user_id`/`agent_id` context (or the app
system identity), so request content cannot forge revision authorship. The
base must equal the current main head or the service returns
`stale_revision_conflict` with expected and actual revision IDs.

## Atomic write boundary

An edit uses `BEGIN IMMEDIATE` and performs, in order:

1. read project/head and check idempotency;
2. verify base revision and preconditions;
3. apply ordered operations to a detached document;
4. fully validate Project IR and compute its digest;
5. insert/reuse the immutable revision;
6. conditionally update the main head and current projection;
7. update persistent undo/redo stacks;
8. record idempotency result and optional autosave;
9. append declared durable outbox records;
10. commit once.

Any validation, SQLite, projection, or outbox failure rolls the transaction
back. Tests force an outbox trigger failure and verify that revision, head,
projection, idempotency, autosave, and outbox counts remain unchanged.

SQLite serializes simultaneous writers. Once the first writer commits, the
second observes a different head and fails stale rather than silently rebasing
or overwriting.

## Persistent undo, redo, and recovery

Undo and redo do not mutate revision content. They atomically move the main
head to an immutable revision while moving the previous head between persistent
JSON navigation stacks. The navigation command itself has a batch ID and is
idempotent. A new edit clears redo history.

All recovery state is in schema v3 SQLite tables. Reopening the service after a
process restart restores the head, stacks, autosaves, idempotency results, and
pending outbox without in-memory reconstruction.

## Native interchange and diff

Native export returns `video-studio-native.v1` with project metadata, revision
ID, digest, and complete Project IR. It contains no executable payload or host
path. Import requires the exact envelope, validates the complete IR in the
trusted workspace, verifies the digest, then creates a normal initial revision
transaction. Optional target project ID/name rebinding is revalidated and
receives a new content digest.

Revision comparison recursively walks sorted object keys and ordered array
positions. Each change has a stable JSON-pointer path and `added`, `removed`, or
`replaced` payload.

## Schema v3 integrity

Migration `0002_project_revision_engine.sql` adds projection, navigation,
operation-batch/idempotency, autosave, and outbox tables plus bounded lookup
indexes. It updates both SQLite `user_version` (through the migration runner)
and app metadata to 2. Migration `0003_revision_integrity.sql` adds immutable
revision and same-project reference triggers and advances both versions to 3.
Migrations 0001 and 0002 and their checksums remain byte-identical.

## Upgrade contract: 0.1.0 / schema 1 to 0.2.0 / schema 3

Video Studio 0.2.0 is the first app source that declares data schema 3. The
built-in source record is version-derived, so normal bootstrap registers a new
`platform:video-studio:0.2.0` source when a workspace is still bound to
0.1.0. Bootstrap invokes the generic install lifecycle for that new source;
the install hook applies every pending migration before Core saves the new
binding and writes the schema marker.

The supported procedure is to deploy the complete 0.2.0 app source and rerun
built-in bootstrap. A successful run preserves schema 1 rows, verifies the
stored checksum for 0001, applies and records 0002 and 0003, advances both
`PRAGMA user_version` and `app_metadata.schema_version` to 3, then publishes
the 0.2.0 binding and schema 3 marker. A second run detects the current source
and binding and does not reapply migrations.

If a pending migration fails, its SQLite transaction is rolled back. Because
the install hook fails before binding and marker publication, the workspace
continues to advertise the previous 0.1.0 / schema 1 state. Do not manually
advance the marker, the metadata row, or `PRAGMA user_version`; correct the
source and retry bootstrap.
