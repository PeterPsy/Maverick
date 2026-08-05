# Generalist And Multi-Agent Orchestration

Date: 2026-07-19
Status: Accepted
Supersedes: the root-transcript projection and Chat-owned topology decisions in
`inter_agent_runtime_invariants.md`

## Purpose

Define the product boundary between the user-visible Chat generalist and a
multi-agent orchestration shown in Agent nodes.

The generalist conversation and the orchestration are two related but
independent runtimes. A user message always enters the normal Chat runtime. An
orchestration request may start beside that turn, but it must never replace the
generalist or reuse the root transcript as its event store.

## Runtime Ownership

- The root Chat runtime session is the independent generalist. Its input,
  output, tools, lifecycle, and transcript remain ordinary runtime records.
- The core `inter_agent` domain owns orchestration runs, participants, edges,
  dependencies, directives, quality decisions, and completion.
- Chat may send an orchestration intent containing the root session, source
  turn, requested policy, and idempotency key. It must not send a participant
  list, edge list, worker prompts, or an execution order.
- An orchestrated run is created with exactly one participant: a real hidden
  child runtime participant of kind `orchestrator`. The orchestrator is visible
  in Agent nodes and absent from the root Chat transcript.
- Only the core may add later participants and edges. Every mutation is
  persisted before work is scheduled and is emitted on the inter-agent event
  stream so replay reconstructs the same graph.
- Creating the board does not launch planning from the raw user prompt. The
  hosted worker waits for the linked generalist turn to reach a successful
  terminal state, persists its final output as
  `inter_agent.generalist.handoff_prepared`, and only then changes the run to
  `planning`.

## Scheduling And Review

The orchestrator produces a bounded initial structured plan. The core validates
that plan and materializes workers from server-authoritative agent snapshots.
The scheduler then runs a persisted adaptive control loop:

1. selects tasks whose declared dependencies have completed, with a narrow
   exception allowing a retry/replacement reviewer to depend on a failed
   reviewer;
2. runs independent ready tasks up to the run concurrency budget;
3. rejects unknown dependencies and dependency cycles before execution;
4. persists task and participant transitions before dispatch;
5. sends every completed or failed worker output back to the orchestrator at a
   safe point;
6. validates and persists the resulting control decision before it adds new
   tasks and edges, cancels unnecessary unstarted work, or completes;
7. repeats output → decision → topology/work until an approved dependent
   reviewer covers the latest completed material frontier of the task DAG,
   follows completed material revision work after every rejected or malformed
   review, causally replaces every failed review, and the orchestrator passes
   the final quality gate.

There is no procedural implementer/reviewer loop in the scheduler. Revisions,
additional research, tests, synthesis, and final review are new structured
tasks chosen by the orchestrator from persisted evidence. The initial plan,
every later decision, task objective, dependency, review target, selected agent
type, attempt, terminal status, and output are replayable event state.

The default `auto`/`multi` policy permits 17 total participants, four concurrent
workers, and 48 total turns. `group_chat` permits 25 participants, six
concurrent workers, and 72 total turns. The initial plan is capped below the
participant budget so later control decisions retain expansion capacity.

A reviewer cannot complete the run. A worker final output cannot complete the
run. Only an explicit orchestrator completion decision can transition an
orchestrated run to `completed`; exhausted revision or budget policy produces a
failed or blocked decision instead of silently accepting work.

## Live Generalist Steering

The source generalist turn is linked to the run by id, not by transcript
projection. Its successful final output is the required launch handoff. Later
Chat messages on the same root session are normal independent generalist turns;
Chat links each accepted turn to the active orchestration instead of creating a
second run. The core waits for that turn at the next safe point and forwards
its bounded final output into the directive channel:

- linked generalist final output, with source turn and runtime event ids;
- direct authorized user steering submitted from the Agent nodes input.

Each generalist link and directive records its source turn, source runtime
event, resolution, and delivery state. The scheduler resolves links and reads
new directives before initial planning and every per-output control decision.
The channel is one-way for transcript isolation: participant runtime events are
never copied into the root runtime store.

Raw reasoning, hidden session ids, unbounded tool payloads, and secret-bearing
runtime data are not valid directives.

Before any later root-session turn is dispatched to its provider, the core
automatically attaches a bounded read-only orchestration projection when that
session has a linked run. The projection contains the run status and summary,
task objectives and progress, bounded result summaries, current quality-gate
frontier, and allowlisted artifact references. It excludes participant runtime
session ids, raw tool payloads, raw reasoning, and artifact bodies. The stored
user message and root transcript remain unchanged; only provider input receives
the projection. Task and result text in the projection is explicitly treated as
untrusted data rather than instructions. This provider-only composition is
identical for synchronous and asynchronous turn submission and applies to both
plain-hosted Chat and agentic runtime workers.

## Transcript Isolation

- The primary Chat transcript reads only the root runtime session.
- Any runtime message carrying an inter-agent participant/run source marker is
  excluded defensively from the primary transcript, including records written
  by older builds.
- Agent nodes reads run detail, the inter-agent WebSocket, and the bounded
  participant transcript endpoint. It does not receive or filter the root Chat
  message array.
- Participant input/output and tool activity stay in hidden runtime sessions
  and safe inter-agent projections. They may appear in Agent nodes only.
- Run summaries and final artifacts remain board data. A generalist may refer
  to them only through an explicit governed read; completion does not inject an
  assistant answer into the root transcript.

## Public Surfaces

The Chat product path is:

- normal runtime turn submission for the generalist;
- `GET /api/inter-agent/generalist-context?root_runtime_session_id=<id>` for
  the same authorized, session-linked read-only projection used automatically
  during provider dispatch;
- `POST /api/inter-agent/orchestrations` with a minimal orchestration intent;
- `POST /api/inter-agent/runs/<run_id>/directives` for authorized user steering;
- existing authorized run detail, replay, participant transcript, approval,
  interrupt, resume, and close surfaces.

The low-level run creation and executor surfaces remain operator/development
surfaces. They are not the Chat submission path and must not regain root
transcript projection behavior.

## Security And Recovery

- The source root session and source turn must belong to the caller's
  workspace, and the caller must satisfy the existing root-session authority
  policy.
- Dynamic workers inherit only server-materialized prompt, skills, provider,
  workspace, and execution authority. Orchestrator output cannot mint grants or
  choose arbitrary prompt/skill material.
- The hosted worker obtains a compact catalog from Chat's selected
  `agent.catalog` provider. An orchestrator may name only one of those agent
  type ids; the core then resolves its definition and prompt through the
  selected provider, validates the runtime skill catalog, and persists the
  resulting immutable participant snapshot. Missing or invalid catalogs fall
  back to the root server snapshot rather than accepting model-authored prompt
  or skill data.
- Hidden participant sessions remain inaccessible through raw runtime HTTP,
  WebSocket, CLI, and MCP paths.
- Orchestrator-authored task ids cannot claim reserved participant identities,
  including the run's actual orchestrator participant id. Recovery may reuse a
  task-id participant only when it is a hidden child-runtime agent whose label,
  selected agent type, task-bound snapshot metadata, digest, skills, and
  provider material match the persisted task. A mismatch fails before any edge
  or task event is added.
- A protected allowlist of state-bearing records in the per-run event partition
  is the recovery ledger for the full plan, adaptive decisions, task attempts,
  directives, quality decisions, and completion. Visibility-history retention
  may prune operational timeline events but never these recovery records;
  internal replay pages to the beginning instead of reading only the newest
  event window. A terminal persisted task participant without a matching result
  record is treated as an incomplete legacy/corrupt ledger and fails recovery
  rather than being rescheduled. A user pause therefore persists a protected
  `cancelled` result for every interrupted active task; the cancelled worker is
  not silently made ready again, including when task execution is between its
  participant claim and child-session creation. The paused status is a global
  scheduler fence, not only a spawn fence. Scheduler transitions, recovery
  records, task materialization, task claim/finalization, directive delivery,
  and completion commit validate both current status and the scheduler's
  captured recovery generation under the workspace transition lock. A queued
  future cannot start after pause, a late worker cannot overwrite a persisted
  cancellation, and the control loop cannot complete a paused run. Pause and
  participant snapshot are one locked transition, so every task claim ordered
  before the pause is reconciled and every claim ordered after it is rejected.
  Runtime turn persistence uses the same locked fence: queueing either precedes
  pause and is visible to interrupt cleanup, or is rejected before any provider
  dispatch. Worker activation then uses a persisted compare-and-set under the
  runtime-session lifecycle handoff, rereading the current turn and session and
  rejecting cancelled turns or non-executable sessions. Provider dispatch then
  repeats that persisted check under the same handoff and retains it through
  the provider acceptance callback, closing the post-activation start window
  without holding a lock for the duration of the turn. Provider and thread
  metadata are partial allowlisted patches under that handoff and cannot restore
  stale lifecycle state after interrupt. A child created
  concurrently is rechecked, deleted, and never linked. Interrupt and resume
  hold the same cross-process run-control handoff across the full cleanup;
  cancellation matches the pause snapshot's generation, runtime session, and
  task. Immediate resume through HTTP, CLI, or MCP next waits for the previous
  hosted scheduler to unwind, resets an interrupted orchestrator onto a new
  recovery-generation child session, and then enqueues the replacement.
  Sidecar-only CLI/MCP execution fails closed when it has no hosted coordinator.
  Hosted backend startup reconciles interrupted participant turns without
  queuing the generic runtime `resume` prompt, resets non-terminal participants onto a new
  recovery-generation child session, and enqueues one scheduler worker for
  each orchestrated run marked `recovering`. Completed tasks are not rerun;
  only persisted pending/dependency-ready work resumes. Each control decision
  is first persisted as `recorded`, then receives a separate idempotent
  `applied` event after cancellations, new task materialization, quality, and
  completion effects succeed. Recovery replays every recorded-but-unapplied
  decision before it materializes or schedules any task. Existing participants
  are recovered from their immutable persisted snapshots without consulting
  the agent catalog; the catalog is used only when a decision introduces a new
  participant. Generic CLI/MCP/test bootstrap does not start those workers.
- A completed negative or malformed reviewer/security-reviewer verdict vetoes
  earlier or parallel approvals. Merely reviewing the same unchanged output
  again is insufficient: the gate can pass only when completed material work
  descends from every such verdict and a later approved review covers the
  resulting frontier.
- A failed reviewer/security-reviewer task is also an unresolved quality
  blocker. It clears only if an approved retry or replacement review has the
  failed task in its transitive dependency ancestry. The scheduler treats a
  failed review as dependency-ready only for a reviewer/security-reviewer
  replacement; material tasks and other roles do not inherit that exception.
- Every `reviewer` and `security_reviewer` task must declare `review_of` and
  directly depend on that target. The core validates this task-local invariant
  for initial plans, adaptive control decisions, and persisted replay payloads;
  an unbound reviewer task is rejected before it can enter scheduler state.
- Recovery rehydrates a persisted initial plan as one atomic unit and reruns
  the same whole-DAG validation used for live planning, including unique and
  non-reserved ids, known dependencies and review targets, and cycle rejection.
  Scheduler state is mutated only after the complete plan passes.
