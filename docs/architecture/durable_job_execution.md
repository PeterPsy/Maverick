# Durable Job Execution

Date: 2026-08-08

## Purpose

`compute.job.execution` version `1` is the generic Maverick capability for work
that must outlive an HTTP request, app entrypoint, or agent turn. Its canonical
submission envelope is `app-job.v1`, defined by
`core/jobs/schemas/app-job.v1.schema.json`.

The core control plane owns scheduling, durable state, executor authority,
quota enforcement, recovery, events, and audit. The executor owns only the
bounded process lifecycle for one registered handler. Apps own handler behavior
and app data, including the resources named by opaque grants. The job domain
must never contain an app product's media types, renderer names, command
templates, or business rules.

The authenticated workspace and actor supplied by HTTP, CLI, or MCP context are
authoritative. The submitted envelope cannot select a different workspace or
actor. The actor is persisted in the immutable spec and correlated with the
submission audit entry.

## State Model

The persisted states are:

- `queued`
- `leased`
- `preparing`
- `running`
- `validating`
- `publishing`
- `succeeded`
- `failed`
- `cancel_requested`
- `cancelled`
- `expired`

`succeeded`, `failed`, `cancelled`, and `expired` are terminal. Success is
accepted only from `publishing`, after the result references have passed the
output grant, MIME, hash, size, and budget checks. Metadata-only jobs must not
publish file references.

Every mutation uses a revision compare-and-set fence. Submission is atomic on
`workspace_id + idempotency_key`; replay of the same canonical spec returns the
existing job even after its grants expire, while reuse with a different
fingerprint is a conflict.

## Grants And Budgets

Input grants carry only an opaque resource reference, digest, size, MIME type,
expiry, and the governed provider interface that issued them. They do not carry
a host or workspace path. A trusted validator for that exact interface must
confirm every input grant at submission and again before lease. Output grants
name a provider interface, accepted MIME types, byte ceiling, and expiry. A job
with output references may succeed only after a registered trusted publisher
for that exact interface promotes or reconciles the references and the core
revalidates them. Missing providers fail closed; the generic core does not
resolve or fabricate an app provider's private storage itself.

The control plane rejects expired grants at submission and lease time. Lease
extensions are capped by input and output grant expiry, the job expiry, and the
runtime timeout. CPU, RAM, GPU, accelerator, disk, runtime, output, duration,
and optional cost declarations are data, not permission to exceed host policy.

Network policy is deny-by-default. `allowlist` is valid only with explicit host
patterns and only on an executor that advertises that network mode.

## Executors

Executors advertise:

- typed handlers and supported handler versions;
- runtimes and versions;
- CPU, RAM, GPU, accelerator, and disk capacity;
- network modes, labels, concurrency, status, and advertisement expiry.

Selection is deterministic and rejects stale, draining, offline, incompatible,
or saturated executors. Capacity checks include resources already leased to the
same executor. Workspace scheduling uses durable last-lease history so repeated
claims rotate among ready workspaces, then honors priority and FIFO order within
one workspace.

The initial server executor is handler-driven. It invokes only importable,
process-safe callables present in an explicit registry whose keys exactly match
the advertisement. Each invocation runs in a separate `forkserver` child with
a private process group, scratch working directory, cleared environment, and a
new user/network namespace. This executor advertises and accepts only enforced
`deny_all` networking. It terminates the whole process group on timeout or
forced cancellation and removes the scratch directory. It does not accept shell
command strings or dynamically evaluate job parameters. The child never
receives the live lease token. A handler receives a bounded
`JobExecutionContext` with the immutable spec plus methods for heartbeat,
cancellation checkpoints, progress, and structured logs. The parent continuously
checks the live lease fence and terminates/reconciles the child immediately when
authority expires or is lost.

Handlers that need external binaries must own a separate governed adapter that
constructs an argv array, applies process-tree timeout and sandbox policy, and
returns a validated result. That adapter is not part of the generic executor.

## Cancellation, Retry, And Recovery

Queued cancellation is immediate. Leased work moves to `cancel_requested` so a
handler can stop at a checkpoint and acknowledge `cancelled`. Trusted operators
may force cancellation; doing so invalidates the lease, so later executor writes
lose their authority.

Retryable failures and expired leases return to `queued` with deterministic
exponential backoff while attempts remain. A hard grant/job/runtime expiry or
an exhausted lease retry budget becomes `expired`. Bootstrap recovery scans the
durable store and applies these same transitions, so restart does not invent a
separate recovery state machine.

## Persistence And Observability

Jobs, events, audits, bounded logs, executor advertisements, and workspace job
quotas are platform control-plane records. They use the configured JSON or
Mongo adapter through `JobDocumentStore`; domain models do not import either
adapter. These collections participate in the normal control-store inventory
and explicit migration process.

Events and audits contain identifiers, state, attempt, revision, bounded
structured progress, and error codes. They intentionally omit free-form
progress and failure text. Executor logs accept a JSON field object bounded to
16 KiB, redact sensitive keys and free-form secret patterns recursively, and
never persist raw exception messages. Retention keeps at most 1,000 records per
job. Event replay, public history, progress fields, and progress text are also
bounded. Public job payloads omit the lease token, and record-aware redaction
removes lease and grant authority values if an executor attempts to repeat them
in progress, cancellation, failure, or log data.

## Public Surfaces

Authenticated workspace HTTP routes are available at `/api/jobs` for submit,
list, detail/history, and cooperative cancellation. The same operations are
available through `core.jobs.submit`, `core.jobs.list`, `core.jobs.get`, and
`core.jobs.cancel` on CLI and MCP. Trusted workspace and actor context are
authoritative; a spec cannot select a different identity. Authenticated clients
receive persisted state changes live through the workspace-filtered
`/api/jobs/events/ws` WebSocket. The connection begins with a
`compute.job.snapshot` containing at most 200 persisted events after an optional
cursor, then sends `compute.job.event` and transport `compute.job.heartbeat`
frames. Ordinary users may request cooperative cancellation; forced HTTP
cancellation requires active workspace-admin or platform-admin authority. CLI
and MCP restrict it to operator contexts. A caller can therefore submit and
observe a durable job without holding the original HTTP request open.

Executor advertisement, claim, heartbeat, stage advancement, completion, and
failure remain trusted service APIs. They require executor identity and the
current opaque lease token; they are not browser operations.

## Known Boundary

Strict queued-count quotas are checked immediately before atomic submission.
The idempotency identity itself is race-safe on both supported adapters. A
future multi-document transactional quota reservation may be required for a
multi-process deployment that needs a mathematically strict simultaneous queue
ceiling; the current check remains deterministic and fail-closed for ordinary
host and sidecar submission paths.

Handler code and registered grant providers are trusted platform integrations,
not an untrusted-code sandbox. The server executor enforces process-tree,
working-directory, environment, runtime, and deny-all network boundaries, but
does not yet provide a private mount namespace, cgroup resource enforcement, or
GPU isolation. Consequently, enabling handlers from an untrusted app package is
out of scope for this checkpoint. Provider callbacks must apply their own
bounded I/O timeouts. The built-in registries intentionally start empty, so a
deployment must register trusted input validators and output publishers before
accepting resource-bearing jobs; metadata-only jobs require neither.
