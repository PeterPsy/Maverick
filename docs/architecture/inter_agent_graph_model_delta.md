# Inter-Agent Graph Model Delta

Date: 2026-06-21
Status: F5.5B design intake

## Purpose

This document compares Maverick's current inter-agent model with LangGraph's graph execution model before Maverick stabilizes a native graph engine or introduces external multi-agent adapters.

The immediate goal is not to import LangGraph. LangGraph is a design reference for graph execution, state, checkpointing, interrupt/resume, replay, bounded loops, conditional routing, and human approval. Maverick remains the owner of product UX, workspace isolation, runtime sessions, authorization, visibility, events, budget, approvals, recovery, and persisted records.

## Source Context

Maverick context:

- Storage blueprint: `storage/generated/specs/maverick_multi_agent_feature_blueprint_2026-06-15.md`
- Current architecture gate: `docs/architecture/inter_agent_runtime_invariants.md`
- Current implementation: `core/inter_agent/models.py`, `core/inter_agent/events.py`, `core/inter_agent/store.py`, `core/inter_agent/service.py`, `core/inter_agent/executor.py`
- Current product surfaces: `core/api/inter_agent_api.py`, `core/api/inter_agent_websocket.py`, `apps/chat/frontend/src/api/interAgent.ts`

LangGraph reference docs consulted:

- [Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Use time-travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)
- [GRAPH_RECURSION_LIMIT](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT)
- [Backward compatibility](https://docs.langchain.com/oss/python/langgraph/backward-compatibility)

## Current Maverick Model

Maverick already has a product-owned inter-agent layer:

- `InterAgentRunRecord` is the lifecycle root for one run.
- `InterAgentParticipantRecord` is the durable product-facing node concept for orchestrators, child agents, tools, humans, and system participants.
- `InterAgentEdgeRecord` stores relationships between participants or graph objects.
- `InterAgentEventRecord` is the normalized replay and audit stream, separated from runtime events and capped by `summary`, `detail`, and `debug` visibility planes.
- `ApprovalRequestRecord` is the durable human approval gate.
- `BudgetPolicyRecord` and `BudgetLedgerRecord` bound participants, concurrency, handoffs, turns, tools, tokens, cost, idle time, and stall time.
- Real child agents run as hidden runtime sessions created only through `InterAgentService`.
- Chat graph mode is a projection over inter-agent records and safe participant transcript projection, not direct access to hidden child sessions.

The current executor is not a generic graph engine. `manager_tools`, `sequential`, and `concurrent` are native executable modes. `handoff`, `group_chat`, and `magentic_like` remain schema/event-only. Edges are persisted, but execution flow is mostly encoded in `core/inter_agent/executor.py`, not in executable edge records.

## LangGraph Model Summary

LangGraph centers execution around:

- `State`: the shared graph snapshot, with schema and reducer behavior.
- `Nodes`: callable units that read state, perform work or side effects, and return state updates.
- `Edges`: fixed or conditional routing functions that choose the next node or nodes based on current state.
- Super-steps: bounded iterations where all scheduled nodes for that tick can execute, including parallel fan-out.
- Checkpointers: thread-scoped graph state snapshots at super-step boundaries, plus task-level writes for successful node outputs inside an in-progress super-step.
- Interrupts: dynamic pauses inside nodes that persist graph state and resume with a caller-provided value.
- Time travel: replay from a prior checkpoint or fork from a prior checkpoint with modified state.
- Recursion limits: runtime bounds for cycles and complex graphs.

Maverick should copy the control ideas, not the dependency or ownership model.

## Delta By Capability

| Capability | LangGraph | Maverick Today | Delta |
|---|---|---|---|
| Nodes | Callable graph nodes operate over shared state. | Participants are durable actor nodes with statuses and runtime linkage. Some graph concepts are implicit in executor code. | Keep participants as product-facing nodes. Add explicit graph execution metadata only when a native graph engine needs private router/system nodes. Do not expose hidden runtime sessions as graph nodes. |
| Conditional edges | Edge functions route based on state and can branch to one node, multiple nodes, `END`, or dynamic sends with per-target state. | `InterAgentEdgeRecord` has source, target, kind, label, and status, but no condition, priority, default branch, fan-out contract, terminal target, or selected-edge payload. | Extend edge records or add graph-edge metadata for `routing_kind`, `condition_ref`, `condition_summary`, `priority`, `is_default`, fan-out behavior, fallback/error routes, and terminal targets. Persist edge evaluation/selection events with selected targets and state patch refs. |
| Bounded loops | Cycles are allowed and bounded by `recursion_limit`, which applies to super-step execution. | Budgets bound participants, turns, handoffs, tools, cost, idle time, and stall time. No super-step, node execution, or edge traversal counter exists. | Define `graph_superstep` as the persisted super-step counter. Add separate budget policy and ledger counters for super-steps, node executions, and edge traversals. |
| State/checkpoint | State schema and reducers define snapshots; checkpointers persist state per thread and pending writes per task. | State is split across run, participant, edge, approval, budget, event, and runtime records. Event replay exists, but no full graph checkpoint, task-write, or reducer model exists. | Add a Maverick-owned checkpoint model with JSON-safe state channels, schema version, reducer ids, next node ids, branch id, parent checkpoint id, task metadata, task-write ids, and state digest. Keep checkpoint/task-write retention separate from event retention. |
| Interrupt/resume | `interrupt()` pauses inside a node, saves state, surfaces JSON payload, then resumes with `Command(resume=...)`. | `interrupt_run` pauses/cancels active child participants and `resume_run` marks the run running. It does not resume from a checkpoint or deliver resume values into node execution. | Add interrupt records tied to checkpoint ids. Resume must accept bounded JSON resume patches, write resume events, update checkpoint state through graph super-step commit, and schedule from saved next node ids. |
| Replay | Replay re-executes from a checkpoint; fork branches from a checkpoint with modified state. | HTTP/WebSocket event replay and history paging exist. Execution replay and fork do not. | Reserve "event replay" for UI/audit and add explicit "checkpoint replay/fork" semantics with side-effect policy. Prefer new child run or branch id rather than mutating completed history. |
| Human approval | Approval is commonly implemented as an interrupt before a critical action, with approve/reject routing. | `ApprovalRequestRecord` is durable, authorized, expiring, and audited. Approval resolution is not yet linked to a graph interrupt resume. | Keep approval records as the authoritative human gate. Link approvals to interrupt/checkpoint/edge ids and route approved/rejected outcomes through explicit graph edges. |

## Record-Level Gaps

### `InterAgentRunRecord`

Current fields are sufficient for lifecycle ownership, root session linkage, visibility, budget, retention, recovery generation, idempotency, and mode.

Needed for a native graph engine:

- `graph_model_version`: identifies the graph semantics used by the run.
- `state_schema_version`: identifies the persisted state channel schema.
- `current_checkpoint_id`: points to the latest resumable checkpoint.
- `active_checkpoint_id`: optional pointer for a paused/interrupted checkpoint.
- `current_graph_superstep`: latest committed graph super-step number.
- `parent_run_id`: optional provenance for forked runs.
- `source_checkpoint_id`: optional checkpoint provenance for replay/fork runs.
- `branch_id`: optional branch identity when multiple trajectories share one logical run family.

Compatibility:

- Existing runs without these fields are `legacy_event_graph` runs. They support event replay but not checkpoint replay/fork.
- Fields must be additive and nullable. Do not rename current status values or mode names during F5.5/F6.

### `InterAgentParticipantRecord`

Current fields are a good fit for product-facing graph nodes because they carry actor kind, execution mode, hidden runtime session linkage, status, skill/provider materialization, authority grants, and sequence order.

Needed for generic node execution:

- `graph_node_id`: optional stable node id when it differs from `participant_id`.
- `node_role`: optional `entry`, `worker`, `router`, `aggregator`, `human_gate`, `tool`, or `terminal`.
- `input_channels` and `output_channels`: optional references to graph state channels used by the participant.
- `retry_policy_ref`: optional policy reference if graph node retries become native.

Compatibility:

- For F6, prefer using existing participant ids as graph node ids.
- Private router nodes can be represented as `kind="system"` and `execution_mode="embedded_executor"` if they need lifecycle visibility. Add a separate `InterAgentNodeRecord` only if non-participant nodes need independent state, authorization, or UI treatment.

### `InterAgentEdgeRecord`

Current fields are sufficient for product graph projection and final-answer source selection, but not for executable routing.

Needed for conditional routing and loops:

- `routing_kind`: `fixed`, `conditional`, `default`, `terminal`, or `loop_back`.
- `condition_ref`: stable id for core-owned condition logic. This must not be arbitrary user code.
- `condition_summary`: user-safe description of the route.
- `priority`: deterministic ordering for multiple matching edges.
- `is_default`: fail-closed default branch marker.
- `target_kind`: `node`, `end`, `fallback`, or `error`.
- `fanout_policy`: `single`, `parallel_targets`, or `dynamic_send`.
- `selection_payload_schema_version`: schema for the edge selection event payload.
- `fallback_edge_id`: fail-closed route when condition evaluation fails.
- `max_traversals`: optional per-edge loop bound.
- `traversal_count`: either persisted on the edge or, preferably, counted in the budget ledger by edge id.

Compatibility:

- Existing edges without routing fields are fixed descriptive edges.
- `kind` remains the product relationship type. Do not overload it with executable routing semantics.
- Keep `target_id` for fixed single-target edges. Conditional fan-out should be represented by selection events and task writes rather than mutating the static edge row into a variable list.

Condition evaluator contract:

- Input: `run_id`, `graph_superstep`, `source_node_id`, `checkpoint_id`, `state_digest`, and the declared state channels allowed by the condition.
- Output: one of `target_node_id`, `target_node_ids`, `END`, `fallback_edge_id`, or `error_edge_id`, plus a user-safe `decision_summary`.
- Dynamic fan-out payloads must be stored as bounded state patches or task writes and referenced from events. Large per-target payloads must not be embedded directly in `inter_agent.edge.selected`.
- A source node must use exactly one routing mechanism in executable mode: static fixed edges, conditional edges, or command-style state-update-plus-routing. Mixing routing mechanisms from the same source is invalid unless a later ADR defines deterministic merge semantics.

Required `inter_agent.edge.selected` payload:

```text
- graph_superstep
- source_node_id
- checkpoint_id
- condition_ref
- evaluated_edge_ids
- selected_targets: list of {edge_id, target_kind, target_node_id, state_patch_ref}
- terminal: bool
- defaulted: bool
- decision_summary
- error_code
```

### `InterAgentEventRecord`

Current events are the right audit/replay backbone. They are already idempotent, sequenced, visibility-capped, and guarded against known unsafe raw-reasoning payload keys.

Needed event types:

- `inter_agent.graph.superstep.started`
- `inter_agent.graph.superstep.completed`
- `inter_agent.edge.evaluated`
- `inter_agent.edge.selected`
- `inter_agent.graph.task.write_created`
- `inter_agent.graph.task.failed`
- `inter_agent.checkpoint.created`
- `inter_agent.checkpoint.restored`
- `inter_agent.replay.started`
- `inter_agent.replay.completed`
- `inter_agent.interrupt.created`
- `inter_agent.interrupt.resumed`

Compatibility:

- Event retention must not be the only copy of checkpoint state. Events can describe checkpoints, but checkpoints need their own retention and recovery policy.
- Event payloads must stay user-safe and must not include raw hidden transcripts, raw chain-of-thought, raw provider state, or secret values.

### `ApprovalRequestRecord`

Current fields cover approval identity, workspace/run/participant linkage, operation kind, resources, summary, risk, status, eligibility, expiry, resolver, and resolution reason.

Needed for graph execution:

- `checkpoint_id`: checkpoint that is waiting on the approval.
- `interrupt_id`: generic interrupt/gate id, if approvals are implemented as graph interrupts.
- `requested_edge_id`: edge or operation that triggered approval.
- `approved_edge_id` and `rejected_edge_id`: explicit routing outcomes.
- `decision_payload_ref`: optional reference to a bounded audit attachment when the approval UI collects structured decision metadata.

Compatibility:

- Existing approval records without graph fields remain valid approval audit records.
- Expiry stays fail-closed. Rejection and expiry must route through explicit graph outcomes or cancel the run.
- Do not store graph resume values directly on `ApprovalRequestRecord`. Approval is the user-facing audit gate; resume values belong to interrupt/checkpoint patch records with their own schema, size limit, retention, and replay policy.

### `InterAgentInterruptRecord`

Maverick does not currently have a generic graph interrupt record. `interrupt_run` is an operational pause/cancel path, while approvals are separate audit records.

Needed for checkpoint-aware resume:

- `interrupt_id`
- `workspace_id`
- `run_id`
- `checkpoint_id`
- `task_id`
- `node_id`
- `participant_id`
- `approval_id`
- `kind`: `approval`, `operator_pause`, `tool_confirmation`, or `external_input`
- `status`: `pending`, `resumed`, `rejected`, `expired`, or `cancelled`
- `prompt_summary`
- `payload_schema_version`
- `resume_patch_ref`
- `resume_patch_digest`
- `max_resume_patch_bytes`
- `retention_policy_id`
- `created_at`
- `resolved_at`

Compatibility:

- Approval-backed interrupts store `approval_id` and approval records store `interrupt_id`, but approval resolution remains audit-first.
- The resume value is stored as a bounded graph patch through the interrupt/checkpoint path, then applied by the graph super-step commit. It is not stored as approval audit payload.

### `BudgetPolicyRecord` And `BudgetLedgerRecord`

Current fields bound resource usage but do not bound graph execution itself.

Needed for loops and graph execution:

- Policy: `max_graph_supersteps`, `max_node_executions`, `max_edge_traversals`, `max_loop_iterations_per_edge`, `max_checkpoints`.
- Ledger: `graph_supersteps_used`, `node_executions_used`, `edge_traversals_used`, `loop_iterations_by_edge`, `checkpoints_created`.

Compatibility:

- Defaults should preserve current behavior: a non-graph run can leave these fields unset or zero-disabled.
- A native graph run must require positive graph bounds before execution.
- `graph_superstep` is the persisted super-step counter. New persistent field names should expose that semantics directly rather than using generic graph-step wording.

## Proposed Checkpoint Model

Add workspace-scoped checkpoint and task-write collections, for example:

```text
workspaces/<workspace_id>/runtime/inter_agent/runs/<run_id>/checkpoints.json
workspaces/<workspace_id>/runtime/inter_agent/runs/<run_id>/task_writes.json
```

Candidate record:

```text
InterAgentCheckpointRecord
- checkpoint_id
- workspace_id
- run_id
- parent_checkpoint_id
- branch_id
- graph_model_version
- state_schema_version
- graph_superstep
- active_node_ids
- next_node_ids
- tasks
- task_write_ids
- writes_by_node
- state_channels
- reducer_versions
- pending_interrupt_ids
- source_event_id
- state_digest
- created_at
```

Rules:

- `state_channels` must be JSON-safe, bounded, and redacted by channel policy.
- Runtime session ids, runtime turn ids, artifact refs, approval ids, and participant ids can be stored as references.
- Hidden runtime transcript content and chain-of-thought must not be copied into checkpoints.
- Reducer behavior must be Maverick-owned and versioned. Persist reducer ids/versions, not Python callables.
- `graph_superstep` is a super-step counter. Parallel nodes scheduled in the same tick share the same `graph_superstep`.
- A full checkpoint is the resume/replay source of truth at a super-step boundary. Events describe what happened around it.
- `tasks` records scheduled node executions for the checkpoint. Each task entry should include `task_id`, `node_id`, `participant_id`, `status`, `error_code`, `error_summary`, `interrupt_ids`, and optional subgraph/checkpoint refs.
- `writes_by_node` maps node ids to committed channel writes from the completed super-step. It is metadata for inspection and replay planning, not the only durable copy of writes.

Candidate task-write record:

```text
InterAgentGraphTaskWriteRecord
- task_write_id
- workspace_id
- run_id
- parent_checkpoint_id
- tentative_checkpoint_id
- graph_superstep
- task_id
- node_id
- participant_id
- status: completed | failed | interrupted | cancelled
- channel_writes
- writes_digest
- error_code
- error_summary
- interrupt_ids
- runtime_session_id
- runtime_turn_id
- side_effect_refs
- idempotency_key
- created_at
```

Rules:

- A node that completes inside a parallel super-step must persist a task-write before the final super-step checkpoint is committed.
- If another node in the same super-step fails, retry/resume must reuse completed task-writes and must not re-run those successful nodes.
- `side_effect_refs` must record idempotency keys or external operation refs for writes that touched files, email, network APIs, provider calls, secrets, or other non-reversible resources.
- Failed and interrupted tasks must be represented explicitly. A missing task-write is not enough to distinguish "not started" from "started and failed before durable output".
- Task writes are not full checkpoints. Time travel and fork resume from checkpoint boundaries; task writes exist for partial recovery inside an in-progress super-step.

## Graph Super-Step Commit Unit

The native graph engine needs one store-level super-step commit operation, not independent calls to save budget, checkpoint, run state, and events.

Candidate operation:

```text
commit_graph_superstep(
  workspace_id,
  run_id,
  idempotency_key,
  parent_checkpoint_id,
  graph_superstep,
  task_writes,
  edge_decisions,
  budget_delta,
  next_checkpoint,
  run_update,
  events,
)
```

Required behavior:

1. Acquire the workspace/run lock.
2. Validate the idempotency key and parent checkpoint.
3. Persist completed task writes and failed/interrupted task records.
4. Mutate budget ledger counters for one super-step, node executions, edge traversals, checkpoints, and loop iterations.
5. Persist the next checkpoint when the super-step is complete, or persist only task writes when the super-step remains partially failed.
6. Update `InterAgentRunRecord.current_checkpoint_id`, `active_checkpoint_id`, `current_graph_superstep`, and status.
7. Append ordered inter-agent events for task writes, edge decisions, checkpoint creation/restoration, interrupts, budget changes, and summary changes.
8. Return the committed checkpoint/task-write ids.

For the JSON store this operation should hold the workspace lock and materialize deterministic records so retries are idempotent. For a future transactional store it should use a transaction or compare-and-swap equivalent. F6 must not stabilize a graph engine that writes these records through unrelated save paths without this commit boundary or an explicit ADR deferral.

## Interrupt And Approval Semantics

Maverick should model a generic interrupt as a graph-level gate and model human approval as one typed gate over that generic mechanism.

Minimum behavior:

1. Before a critical tool, external write, high-cost action, or human gate, executor creates a checkpoint.
2. Executor writes `inter_agent.interrupt.created`.
3. If the gate is approval-backed, executor creates `ApprovalRequestRecord` and writes `inter_agent.approval.requested`.
4. Run status becomes `waiting_approval` for approval gates or `paused` for generic operator pauses.
5. Approval resolution writes `inter_agent.approval.resolved`.
6. Resume writes `inter_agent.interrupt.resumed`, resolves a bounded `resume_patch_ref`, applies that patch to graph state through the checkpoint path, and schedules from checkpoint `next_node_ids`.
7. Rejection, expiry, or unauthorized resolution routes to an explicit rejected edge, cancels the pending action, or cancels the run.

Side effects before an interrupt must be idempotent. If a side effect cannot be made idempotent, the interrupt must occur before that side effect.

## Replay And Fork Semantics

Maverick currently supports event replay for graph UI and audit. That is not execution replay.

Native checkpoint replay should use explicit operations:

- `replay`: re-execute from a checkpoint with the same state and graph model version.
- `fork`: create a new trajectory from a checkpoint with a sanitized state patch.

Default policy:

- Completed history is immutable.
- Fork should prefer a new `InterAgentRunRecord` linked by `parent_run_id` and `source_checkpoint_id`, unless a later ADR chooses branch-in-run UX.
- Replay/fork must default to side-effect-blocked or approval-required for external writes, tool calls with real-world effects, email sends, file mutation, secret use, and paid provider calls above policy.
- Synthetic/test replay can be enabled in tests and explicit operator flows.

## Design Reference Scenarios

### Checkpoint, Interrupt, Resume

1. A graph run reaches a human gate before a storage write.
2. Executor creates checkpoint `cp-1` with `next_node_ids=["write_file"]`.
3. Executor creates interrupt `int-1` and approval `apr-1`.
4. Chat renders approval from `ApprovalRequestRecord`.
5. User approves.
6. Core writes approval and interrupt resume events.
7. Core stores an interrupt resume patch such as `{approved: true}` under the interrupt/checkpoint retention policy.
8. Executor restores `cp-1`, applies the resume patch, selects the approved edge, and runs `write_file`.

Acceptance signal: the write cannot occur before approval; replay from `cp-1` does not duplicate any pre-approval side effect.

### Parallel Partial Recovery

1. A super-step schedules `node_a` and `node_b` in parallel.
2. `node_a` completes, writes an external artifact, and persists `InterAgentGraphTaskWriteRecord` with `side_effect_refs` and idempotency refs.
3. `node_b` fails before the full super-step checkpoint can be committed.
4. Run status becomes `recovering` or `failed` with task-level failure metadata.
5. Resume/retry reads task writes for the in-progress super-step, reuses `node_a` output, and only re-runs unresolved or failed tasks.

Acceptance signal: successful parallel work is not recomputed after a sibling task fails, and external side effects from successful tasks are not duplicated.

### Conditional Edges And Bounded Loop

1. Router participant evaluates a draft quality score.
2. If score is below threshold and loop count is below policy, select `revise` edge.
3. If loop count reaches the edge traversal or super-step limit, select `fallback_summary` or `END`.
4. Every edge evaluation and selection is persisted as events.
5. Budget ledger increments `graph_supersteps_used`, `node_executions_used`, and `edge_traversals_used` atomically inside the graph super-step commit.

Acceptance signal: a bad routing condition cannot create an unbounded loop; limit exhaustion produces a visible summary event and terminal/fallback behavior.

### State Model

1. Input channel stores the user request.
2. Participant output channel stores declared summaries and artifact refs.
3. Approval channel stores approval ids and sanitized decisions.
4. Runtime transcript remains in runtime records and is projected safely when requested.
5. Checkpoints persist channel values and reducer versions, not hidden raw session internals.

Acceptance signal: graph execution can resume from checkpoint after restart without exposing hidden runtime transcripts or raw reasoning.

## Decisions For F5.5B

1. Maverick keeps participants as the product-facing node model.
2. Maverick adds graph execution semantics as additive metadata and records, not by replacing `InterAgentRun/Participant/Edge/Event`.
3. Event replay remains the source for Agent nodes UI and audit history.
4. Checkpoint replay/fork is a separate future execution capability.
5. Human approval remains Maverick-owned through `ApprovalRequestRecord`; LangGraph-style interrupts inform the resume/checkpoint mechanics only.
6. Task-level writes are required for partial recovery before a native graph engine is stabilized.
7. Graph execution persistence requires an explicit graph super-step commit boundary.
8. Any F6 adapter must map immediately into current Maverick run, participant, edge, event, budget, approval, and artifact contracts. It must not write participant output to the root transcript or own sessions, secrets, providers, retention, approval, replay, workspace isolation, or any deferred native graph records.
9. Checkpoint, task-write, generic interrupt, executable routing, graph super-step, and replay/fork concepts remain Maverick-native future contracts unless explicitly implemented by a later ADR. F6 may expose only safe observed adapter decisions through existing `InterAgentEventRecord` payloads.

## F6 Scope Decision Table

This table closes the F6 scope decision required by the blueprint. It intentionally does not turn every LangGraph delta into immediate MAF work.

| Gap | Implementare prima di F6? | Rinviare? | Owner | Motivazione | Test compensativi |
|---|---|---|---|---|---|
| Checkpoint full | No | Si, prima di stabilizzare il graph engine nativo | `core/inter_agent` graph engine ADR | Full checkpointing requires state channels, reducer versions, retention, checkpoint ids, and resume/replay policy. F6 only needs an adapter boundary and event projection. | F6 adapter tests assert no checkpoint ids, checkpoint replay, fork API, or checkpoint files are produced; event replay remains UI/audit only; restart/cancel/failure use existing run, participant, artifact, budget, and event records. |
| Task-write partial recovery | No | Si, prima di parallel graph execution nativa | `core/inter_agent` recovery/store | Task writes matter when parallel nodes share a super-step and one sibling fails after durable side effects. F6 fixtures can fail closed without promising partial graph recovery. | Source-backed concurrent/group fixtures persist artifact/event refs before failure; cancel/retry assertions prove event sequence and budget reservation idempotency; tests explicitly document that partial task recovery is unsupported in F6. |
| Graph super-step commit | No | Si, prima del graph engine nativo | `core/inter_agent` store | A store-level graph commit is required only when checkpoint, task writes, edge decisions, budget deltas, and run state become one atomic graph step. F6 must not fake that boundary through adapter state. | Adapter tests assert writes go through existing inter-agent service/store paths, event sequence/idempotency remains stable, terminal run status is coherent, and no checkpoint/task-write collections are created. |
| Replay/fork execution | No | Si, dopo side-effect policy e checkpoint model | `core/inter_agent` HTTP/CLI/MCP with recovery/security review | Maverick already has event replay for Agent nodes and audit. Execution replay/fork can duplicate side effects unless checkpoint, approval, and side-effect policy are designed first. | F6 replay tests cover HTTP/WebSocket event replay only; no execution replay/fork endpoints are exposed; event replay must not invoke adapter, provider, tool, file, email, or paid side effects. |
| Generic interrupt record | No | Si, dopo checkpoint-aware resume design | `core/inter_agent` approvals/runtime | Current `interrupt_run`/`resume_run` are operational pause controls and `ApprovalRequestRecord` is the human gate. A generic interrupt record needs checkpoint ids and bounded resume patches. | HITL in F6 maps to `ApprovalRequestRecord` plus existing pause/resume/close behavior; tests cover approve, reject, expiry, unauthorized resolution, pause, close, and absence of resume patch payloads. |
| Conditional routing metadata | Solo eventi minimi osservabili | Si, per routing eseguibile, `condition_ref`, fan-out e loop edges | `core/inter_agent/adapters` with graph ADR owner | MAF fixtures need visible speaker/route/handoff decisions, but executable conditional edges are part of the future Maverick-native graph model and must not be owned by MAF. | Adapter fixtures emit safe summary/detail event payloads with route or speaker decision summaries, correlation ids, idempotency keys, participant ids, and visibility planes; tests assert no arbitrary condition code, no `inter_agent.edge.selected` semantics, and no executable edge mutation. |
| Loop budget fields | No new graph fields; map temporary loops to existing budgets | Si, for `max_graph_supersteps`, node executions, edge traversals, and per-edge loop counters | `core/inter_agent` budget/adapters | F6 can bound adapter loops through existing `max_rounds`, `max_total_turns`, `max_handoffs`, `max_tool_calls`, idle, and stall budgets. Native graph counters remain separate future fields. | MAF group/magentic fixtures force max-round or max-turn exhaustion; tests expect visible budget/failure summaries and no unbounded loop; existing budget reservation and release idempotency remains covered. |
| MAF adapter event mapping | Si | No | `core/inter_agent/adapters` | This is the only F6-critical LangGraph/MAF delta: the adapter must become observable through Maverick-owned records without owning runtime, provider, secret, approval, budget, or retention state. | Source-backed handoff, group chat, and magentic fixtures assert mapping into `InterAgentEventRecord`, participants, edges/artifacts where applicable, approval/budget records when used, safe visibility planes, no raw MAF payloads, cancel/failure/event-replay coverage, package pin, and feature flag. |

## Open Implementation Work Before Stabilizing A Graph Engine

Rows marked as deferred above remain open before Maverick stabilizes a native graph engine. They are not prerequisites for starting the F6 MAF adapter unless the adapter attempts to expose the deferred behavior as runtime semantics.

- Add checkpoint, task-write, and interrupt records.
- Add the graph super-step commit operation.
- Add graph super-step, node-execution, and edge-traversal budget fields, or deliberately adopt a narrower native-graph loop model in a later graph-engine ADR.
- Add executable edge routing metadata and edge evaluation/selection events, including fan-out, `END`, fallback, error, and dynamic-send semantics.
- Add checkpoint-aware resume semantics.
- Define replay/fork HTTP, CLI, and MCP surfaces with side-effect policy.
- Add migration handling for legacy event-only runs.
- Add tests for checkpoint/interrupt/resume, task-write partial recovery, graph super-step commit idempotency, conditional edges/loop bounds, approval routing, recovery after restart, and event-vs-checkpoint replay separation.

## Gate

F6 adapter work can proceed only if this delta and the F6 scope decision table remain accepted. F6 is blocked if adapter work requires checkpoint replay, task-write recovery, generic interrupt resume patches, executable conditional routing, or graph super-step commit semantics. The native graph engine must not stabilize persistent semantics before checkpoint, task writes, graph super-step commit, conditional routing, loop bounds, interrupt/resume, replay/fork, and approval routing are represented in Maverick-owned contracts.
