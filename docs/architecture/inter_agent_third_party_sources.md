# Inter-Agent Third-Party Sources

Date: 2026-06-21
Status: F5.5A source intake manifest

## Purpose

This manifest authorizes the first third-party adapter candidate for Maverick F6.
It does not install any package and does not create the adapter implementation.

The adapter boundary remains Maverick-owned. Third-party frameworks may supply
orchestration mechanics, but they must not become the owner of runtime sessions,
provider selection, secrets, retention, replay, budget, approvals, workspace
isolation, transcript visibility, or product UI payloads.

## Decision

Microsoft Agent Framework is the first experimental adapter candidate for F6.

LangGraph remains graph execution design reference.

OpenAI Agents SDK is not selected for F5.5A or F6, and this manifest records
no source pin for it.

## Source Pin

### Microsoft Agent Framework

- Upstream repository: `https://github.com/microsoft/agent-framework`
- GitHub source tag: `python-1.9.0`
- GitHub commit: `b55992bb679602a6615d4f1a1c273bcc59751bf4`
- Verification date: 2026-06-21 UTC
- Upstream license: MIT
- Upstream release context: PyPI lists `agent-framework` and
  `agent-framework-core` version `1.9.0` as released on 2026-06-18.

Selected Python packages for F6:

| Package | Pin | Role | Why selected |
|---|---:|---|---|
| `agent-framework-orchestrations` | `==1.0.0` | Required F6 package | Provides the orchestration builders needed for source-backed `handoff`, `group_chat`, and `magentic` fixtures: `HandoffBuilder`, `GroupChatBuilder`, and `MagenticBuilder`. |
| `agent-framework-core` | `==1.9.0` | Direct companion pin | Required by `agent-framework-orchestrations` as `>=1.9.0,<2`; Maverick pins it directly so F6 does not float within that range. |

Package intentionally not selected for F6:

| Package | Status | Reason |
|---|---|---|
| `agent-framework` | Not selected | It depends on `agent-framework-core[all]==1.9.0`, which expands to many optional integrations. F6 needs the orchestration adapter boundary, not the full integration bundle. |
| `agent-framework-foundry` | Not selected by default | Upstream samples use Foundry clients, but Maverick must own provider selection and secret resolution. Add only under a later provider-specific test plan with an explicit pin and secret-policy review. |
| `agent-framework-openai` | Not selected by default | Provider integration must remain Maverick-owned. F6 adapter tests should use Maverick-controlled fakes or injected provider handles, not direct package-level OpenAI credential lookup. |
| OpenAI Agents SDK | Not selected | Outside F5.5A/F6 because F6 is MAF-first and LangGraph is the graph execution design reference. Do not add this package unless a later source intake pins and reviews it. |

Pin rationale:

- The selected package is the narrowest currently visible PyPI package that
  directly names the three required F6 patterns.
- The metapackage is rejected because it installs optional integrations that
  would widen dependency, provider, and secret surfaces before Maverick has an
  adapter implementation.
- The upstream repository tag and the PyPI package versions were verified on
  the same date. F6 implementation must re-check both before adding dependency
  declarations.

When F6 actually introduces dependencies, add the selected pins to the narrowest
appropriate optional dependency group in `pyproject.toml`, not to default runtime
dependencies, unless a later ADR explicitly makes MAF a default runtime
dependency.

## License And NOTICE

MAF is MIT licensed.

If F6 adds MAF as a dependency:

- update `pyproject.toml` with exact pins;
- regenerate `docs/legal/third_party_inventory.json` with
  `python3 scripts/generate_dependency_inventory.py`;
- review `docs/legal/third_party_inventory.md` if the inventory process changes;
- run dependency and import verification appropriate to the new optional group.

If F6 copies any upstream sample, snippet, fixture code, or test helper:

- preserve the upstream Microsoft copyright notice in the copied file when the
  copied code is substantial enough to be copyrightable;
- include an MIT attribution note near the copied fixture or in a future
  repository NOTICE file if one is introduced;
- record the exact upstream URL, tag, and commit beside the copied fixture;
- prefer adaptation from documented behavior over copying source code.

F5.5A copies no MAF code. This manifest records sources and intended fixture
adaptations only.

## Feature Flag

F6 adapter code must be disabled unless this explicit environment flag is set:

```text
MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK=1
```

The flag gates experimental adapter registration and execution. This F6
exception is for source-backed adapter evaluation only: it is not default-on,
not product-facing Chat behavior, and not a promotion of `handoff`,
`group_chat`, or `magentic_like` to native executable MVP modes. The schema,
event records, budget records, approval records, and safe UI projections remain
Maverick-owned and must not depend on the flag for validation.

## Target Maverick Files

Future F6 adapter-specific implementation starts with these initial source
targets:

```text
core/inter_agent/adapters/__init__.py
core/inter_agent/adapters/base.py
core/inter_agent/adapters/maf.py
tests/unit/inter_agent/test_maf_handoff_adapter.py
tests/unit/inter_agent/test_maf_group_chat_adapter.py
tests/unit/inter_agent/test_maf_magentic_adapter.py
tests/integration/inter_agent/test_maf_handoff_fixture.py
tests/integration/inter_agent/test_maf_group_chat_fixture.py
tests/integration/inter_agent/test_maf_magentic_fixture.py
tests/support/maf_group_chat_fixture.py
tests/support/maf_magentic_fixture.py
```

F6 may also touch the narrowest supporting files needed for the declared
optional dependency, legal inventory, package export, and feature-flag
registration work, including:

```text
pyproject.toml
docs/legal/third_party_inventory.json
```

Review `docs/legal/third_party_inventory.md` only if the inventory process
changes.

Any registration wiring must stay inside existing core-owned inter-agent or
configuration boundaries. F6 must not add product-facing Chat modes, new
execution replay/fork endpoints, provider-specific packages, or UI payload
surfaces unless a later Maverick-owned ADR expands the scope.

Do not create the adapter-specific files or change dependency declarations in
F5.5A.

## Fixture Source-Backed F6

The fixtures below are adapter/evaluation fixtures only. They are not
product-facing modes, not default-on, and not a replacement for Maverick-native
graph execution.

### MAF `handoff`

- Upstream source:
  `https://github.com/microsoft/agent-framework/blob/python-1.9.0/python/samples/03-workflows/orchestrations/handoff_simple.py`
- Upstream implementation source:
  `python/packages/orchestrations/agent_framework_orchestrations/_handoff.py`
- What is adapted:
  triage-to-specialist transfer decisions and `handoff_sent` workflow events.
  Provider clients, Azure credential lookup, environment variables, sample
  business tools, and raw transcript printing are not adapted.
- Maverick events emitted:
  `inter_agent.mode.selected`, `inter_agent.participant.started`,
  `inter_agent.handoff.requested`, `inter_agent.handoff.accepted`,
  `inter_agent.handoff.completed`, `inter_agent.message.sent`,
  `inter_agent.summary.updated`, and terminal run events as applicable.
- Budget limits used:
  `max_handoffs`, `max_total_turns`, `max_turns_per_participant`,
  `max_tool_calls`, `max_idle_seconds`, and `max_stall_seconds`.
- Not product-facing:
  no handoff composer mode, no raw MAF event console, no direct child runtime
  session link, and no hidden transcript exposure.

### MAF `group_chat`

- Upstream sources:
  `https://github.com/microsoft/agent-framework/blob/python-1.9.0/python/samples/03-workflows/orchestrations/group_chat_simple_selector.py`
  and
  `https://github.com/microsoft/agent-framework/blob/python-1.9.0/python/samples/03-workflows/orchestrations/group_chat_agent_manager.py`
- Upstream implementation source:
  `python/packages/orchestrations/agent_framework_orchestrations/_group_chat.py`
- What is adapted:
  bounded speaker selection, manager-directed speaker decisions, intermediate
  participant output, and terminal workflow output. The selection function is
  observed and summarized; it is not converted into executable Maverick
  conditional edges.
- Maverick events emitted:
  `inter_agent.mode.selected`, `inter_agent.participant.started`,
  `inter_agent.task.started`, `inter_agent.message.sent`,
  `inter_agent.summary.updated`, `inter_agent.task.completed`, and terminal run
  events as applicable. Safe speaker decisions may be included in detail-plane
  payload summaries with correlation ids and idempotency keys.
- Budget limits used:
  `max_rounds`, `max_total_turns`, `max_turns_per_participant`,
  `max_concurrent_participants`, `max_idle_seconds`, and `max_stall_seconds`.
- Not product-facing:
  no group-chat mode in Chat, no manager debug UI, no raw MAF state, and no
  executable route mutation in `InterAgentEdgeRecord`.

### MAF `magentic` / manager

- Upstream source:
  `https://github.com/microsoft/agent-framework/blob/python-1.9.0/python/samples/03-workflows/orchestrations/magentic.py`
- Upstream implementation source:
  `python/packages/orchestrations/agent_framework_orchestrations/_magentic.py`
- What is adapted:
  manager planning/progress observations, participant request dispatch, bounded
  intermediate participant output, and terminal manager output. Hosted tools,
  code-interpreter setup, manual console input, and provider-specific clients
  are not adapted.
- Maverick events emitted:
  `inter_agent.mode.selected`, `inter_agent.plan.summary_created`,
  `inter_agent.participant.started`, `inter_agent.task.started`,
  `inter_agent.message.sent`, `inter_agent.summary.updated`,
  `inter_agent.task.completed`, `inter_agent.budget.exceeded` when limits
  trigger, and terminal run events as applicable.
- Budget limits used:
  MAF sample limits `max_round_count`, `max_stall_count`, and
  `max_reset_count` map to Maverick-owned `max_rounds`,
  `max_total_turns`, `max_idle_seconds`, and `max_stall_seconds`. Tool usage
  maps to `max_tool_calls` only when Maverick has explicitly registered a
  tool proxy and budget reservation.
- Not product-facing:
  no Magentic mode selector, no plan-review UI, no code interpreter exposure,
  no raw progress ledger in the UI, and no checkpoint or replay/fork semantics.

## Acceptance Criteria

F6 passes only if all of the following are true:

- MAF does not own runtime sessions.
- MAF does not own provider selection.
- MAF does not receive secrets directly.
- MAF does not own retention or replay.
- MAF workflow events are translated into `InterAgentEventRecord`.
- Cancel, failure, and event replay are tested.
- Execution replay/fork is not implemented or tested as an F6 adapter
  capability.
- No raw MAF payload reaches the UI.
- MAF is registered only when `MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK=1`.
- Dependencies remain selective and pinned.
- Provider-specific packages are absent unless a later provider-specific test
  plan explicitly pins and reviews them.

## F6 Adapter Acceptance Matrix

| Scenario | Source-backed fixture | Replay / idempotency | Cancel / failure coverage | Safe payload / no raw adapter state | No provider, secret, or session ownership | Feature flag |
|---|---|---|---|---|---|---|
| Handoff | `tests/integration/inter_agent/test_maf_handoff_fixture.py` runs `HandoffBuilder` with controlled fake chat clients. | Unit and integration tests remap and append retry batches with stable event ids and idempotency keys. | Handoff lifecycle covers requested, accepted, and completed events; cancellation remains covered by group chat fixture for F6 adapter terminal behavior. | Payload assertions reject raw payload, chain-of-thought, provider, secret, session, route, and edge material. | Participant assertions require empty provider/runtime session/grant ownership. | `MafAdapter.require_available()` and CI run behind `MAVERICK_EXPERIMENTAL_AGENT_FRAMEWORK=1`. |
| Group chat | `tests/integration/inter_agent/test_maf_group_chat_fixture.py` runs selector, manager, max-rounds, and cancellation fixtures with controlled fake chat clients. | Unit and integration tests append original and retry batches and replay ordered event pages. | Max-rounds maps to budget exceeded plus run failed; cancellation maps to run cancelled while participant is running. | Payload assertions reject raw MAF state, transcripts, provider, secret, session, route, and edge material. | Participant assertions require empty provider/runtime session/grant ownership and no executable edges. | Included in the `inter-agent-maf` CI job under the explicit feature flag. |
| Magentic / manager | `tests/integration/inter_agent/test_maf_magentic_fixture.py` runs `MagenticBuilder` with a controlled fake `manager_agent` and participant fake providers. | Unit and integration tests remap, append, retry, and replay plan/progress/dispatch/output/terminal records. | Stall observations map to safe summary fields; max-rounds maps to budget exceeded plus run failed. | Payload assertions reject raw progress ledger, raw payload, transcripts, provider, secret, session, checkpoint, task-write, route, and edge material. | Participant assertions require empty provider/runtime session/grant ownership and no executable edges. | Included in the `inter-agent-maf` CI job under the explicit feature flag. |

## Graph Delta Deferrals

F6 must follow
[inter_agent_graph_model_delta.md](inter_agent_graph_model_delta.md).

```text
checkpoint, task-write, super-step commit, generic interrupt e replay/fork sono deferred per F6.
L'adapter MAF non puo introdurli come semantica proprietaria.
```

Checkpoint, task-write, super-step commit, generic interrupt and replay/fork
are deferred for F6.

The MAF adapter cannot introduce them as proprietary semantics.

The F6 adapter may emit safe observations of MAF routing, speaker, handoff,
planning, progress, cancellation, and failure behavior through existing
`InterAgentEventRecord` types. It must not add checkpoint ids, task-write
records, graph super-step records, generic interrupt resume patches, execution
replay/fork endpoints, or executable conditional route records unless a later
Maverick-owned ADR changes the graph model.

## Non-Goals For F5.5A

- Do not install MAF.
- Do not create `core/inter_agent/adapters/maf.py`.
- Do not add OpenAI Agents SDK.
- Do not implement checkpoint, task-write, super-step, generic interrupt, or
  replay/fork execution semantics.
- Do not make MAF the runtime owner.
