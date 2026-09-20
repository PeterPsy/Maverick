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

## Antigravity

Antigravity is a `native_agent` using its installed structured CLI, an isolated
runtime home and the operator-managed OAuth connection. Activation requires a
successful live model discovery; enabled workspace bindings then behave like
other CLI model choices without exposing OAuth or runtime internals in the UI.
Catalog aliases that differ only by a `high`, `medium`, or `low` suffix are
projected as one stable model choice with those values as reasoning efforts.
At launch the selected effort resolves back to the matching authenticated CLI
catalog alias.

Native CLI engines share one execution contract. In sandbox mode Maverick
confines the process and dependencies while leaving the selected workspace
writable. In full-access mode it launches the reviewed CLI directly with that
CLI's non-interactive permission bypass. The provider home remains private in
both modes. Native runtimes own their structured tool surface, so an empty
Maverick hosted-tool handle list does not erase their declared CLI, filesystem,
shell, or MCP capabilities.
Antigravity skills are mounted from its private canonical config tree; the
CLI-managed compatibility alias is accepted only when it resolves back to that
exact tree, so process and backend restarts preserve the boundary.
The launch registers the workspace explicitly as well as setting cwd.
Antigravity receives the workspace instructions, agent instructions and skill
catalog that Codex discovers natively. Both use the same enabled,
session-allowed skill resolver; an implicit session does not require a user
skill invocation to receive its catalog.

## Hosted Maverick agents

OpenRouter GLM and OpenRouter DeepSeek Flash Latest are `maverick_agent`
configs. Core owns their tool loop, context, accounting, provider-private state
and recovery. Each config declares its exact endpoint, provider/model protocol,
route and reasoning. Google AI Studio is not published as an API-agent choice;
Google agent models are exposed through the Antigravity CLI family instead.
DeepSeek Flash Latest uses the OpenRouter alias
`~deepseek/deepseek-flash-latest` so OpenRouter advances the underlying Flash
model without creating a text-only choice. Streaming identity validation accepts
only the requested alias or one of that config's explicitly pinned resolved
model ids; arbitrary revisions and upstreams still fail closed.

The runtime resolves credentials and health immediately before use. It exposes
only tools allowed by the current workspace, actor, execution mode and policy.
No Full Workspace contract, harness digest or vendor-catalog digest is required
to make the model selectable.
API adapters consume the same Core semantic context before their transport
codecs render it. Runtime context uses real workspace/workdir paths
for full-access tools and `workspace://<id>/<relative-workdir>` for sandbox
tools, preserving nested working directories without exposing sandbox host
paths. The environment projection is shared with native CLI context; workspace
instructions, agent instructions, references and invoked skills keep their
existing classified semantic blocks.

## Internal text generation compatibility

Plain hosted text is not a selectable Chat model family and cannot create a new
composer choice. The lower-level hosted-text path remains only for internal
generation and compatibility with already-persisted sessions. Speech STT and
TTS are separate provider contracts and are unaffected.

## Failure behavior

A new agentic session is rejected only for a real unmet dependency or policy:
disabled/missing workspace config, unauthorized actor, missing credential,
unhealthy runtime, unsupported model/reasoning, invalid route, denied execution
mode, tool policy or egress.

An existing incompatible session returns `runtime_session_restart_required`.
Core does not migrate it at bootstrap or create a compatibility fork.
