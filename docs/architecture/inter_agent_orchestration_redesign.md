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

## Scheduling And Review

The orchestrator produces a bounded structured plan. The core validates that
plan and materializes workers from server-authoritative agent snapshots. The
scheduler then:

1. selects only tasks whose declared dependencies have completed;
2. runs independent ready tasks up to the run concurrency budget;
3. rejects unknown dependencies and dependency cycles before execution;
4. persists task and participant transitions before dispatch;
5. pairs implementation work with review when the plan requests a quality
   gate;
6. returns reviewer feedback to a new implementation attempt while revision
   and turn budgets remain;
7. asks the orchestrator for the final quality/completion decision using the
   persisted outputs and reviewer verdicts.

A reviewer cannot complete the run. A worker final output cannot complete the
run. Only an explicit orchestrator completion decision can transition an
orchestrated run to `completed`; exhausted revision or budget policy produces a
failed or blocked decision instead of silently accepting work.

## Live Generalist Steering

The source generalist turn is linked to the run by id, not by transcript
projection. The core forwards a bounded, user-safe subset of root runtime
events into the inter-agent directive channel:

- generalist output updates and final output;
- explicit generalist status or tool-result summaries that contain text;
- user steering submitted from the Agent nodes orchestrator input.

Each directive records its source session, source turn, source runtime event,
and delivery state. The scheduler reads newly persisted directives before each
planning, scheduling, revision, and completion decision and includes them in
the next orchestrator turn. The channel is one-way for transcript isolation:
participant runtime events are never copied into the root runtime store.

Raw reasoning, hidden session ids, unbounded tool payloads, and secret-bearing
runtime data are not valid directives.

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
- Hidden participant sessions remain inaccessible through raw runtime HTTP,
  WebSocket, CLI, and MCP paths.
- The event store is the recovery log for graph mutation, directives, quality
  decisions, and completion. Recovery resumes only persisted ready work and
  never replays a participant event into the root transcript.
