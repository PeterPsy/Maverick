# Runtime Provider Model

This reference describes the current direct provider and agentic runtime model.

## Provider roles

- `runtime_engine`: owns an agent loop, for example Codex.
- `model_provider`: exposes a hosted inference API, for example OpenRouter.
- `speech_provider`: exposes speech-specific operations.

Credentials are Core secrets referenced by binding id. Public APIs return only
redaction-safe metadata.

## Execution families

| Family | Loop owner | Workspace actions |
| --- | --- | --- |
| `native_agent` | Native structured runtime | Yes, under Maverick supervision |
| `maverick_agent` | Maverick Core | Yes, through Core tools |
| `hosted_text` | No action loop | No |

Family is derived from the runtime implementation. It is not profile rollout
state and is not stored in `RuntimeExecutionBinding`.

## Current agentic config

An `AgenticProfileDefinition` directly declares the current:

- runtime, adapter, provider, model and protocol;
- model revision policy and routing constraint;
- supported/default reasoning;
- capability set and policy ceiling;
- egress and context policy.

A `WorkspaceAgenticProfileBinding` selects one definition and contains enable,
default, credential reference, actor policy and workspace policy narrowing.
Definitions and bindings have no revision lineage or rollout status.

## Session binding

`RuntimeExecutionBinding` stores only the concrete inputs required to continue a
session: session/workspace/workspace-binding ids; runtime/adapter;
provider/model/protocol/route; credential; reasoning; capabilities; execution
mode; runtime and egress policy; context/model settings; and creation time.

There is no profile revision, binding revision, execution family, recipe,
provider catalog/config identity metadata or binding digest in this record.

## Live authority

For every turn Core derives `RuntimeAuthority` and checks the current enabled
workspace binding, actor policy, credential availability, runtime health,
execution mode, feature flags, route/upstream, tool permission and egress. The
result can only narrow the session's capabilities. It is ephemeral runtime
authorization, not model certification or availability state.

## Codex

Codex is a `native_agent` using `codex-app-server`. Its current model and
reasoning catalog is discovered from the installed runtime. Each model has one
stable direct config. A successful refresh updates discovery; a failed refresh
keeps the last usable snapshot and has no expiry deadline.

The workspace default is selected by its direct binding. New sessions may pick
another enabled current model and supported reasoning effort.

## Hosted Maverick agents

Google Gemini and OpenRouter GLM are `maverick_agent` configs. Core owns their
tool loop, context, accounting, provider-private state and recovery. Each config
declares its exact endpoint, provider/model protocol, route and reasoning.

The runtime resolves credentials and health immediately before use. It exposes
only tools allowed by the current workspace, actor, execution mode and policy.
No Full Workspace contract, harness digest or vendor-catalog digest is required
to make the model selectable.

## Hosted text

Text-only models use `HostedTextExecutionBinding` and the no-tools hosted-text
path. This is separate from agentic model configuration.

## Failure behavior

A new agentic session is rejected only for a real unmet dependency or policy:
disabled/missing workspace config, unauthorized actor, missing credential,
unhealthy runtime, unsupported model/reasoning, invalid route, denied execution
mode, tool policy or egress.

An existing incompatible session returns `runtime_session_restart_required`.
Core does not migrate it at bootstrap or create a compatibility fork.
