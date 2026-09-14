# Native Agent Admission

Native agent admission is driven by the current installation contract, live
model catalog, direct agentic profile and workspace policy.

## Connection contract

A native installation declares its runtime engine, adapter/version, structured
protocol, harness recipe, model-provider connection, sandbox/effect mapping and
Full Workspace revision. Registration validates those fields and the callable
lifecycle controller.

The connection is model-catalog scoped rather than a hard-coded slug allowlist.
An authenticated catalog refresh reconciles immutable model projections. A new
model slug does not require a separate Maverick issuance step. A removed or
ambiguous model is unavailable for new sessions.

## New-session admission

Core admits a native session only when:

- the provider and profile rollout are enabled;
- an enabled workspace binding selects the exact profile;
- the runtime is installed and healthy;
- the current catalog contains the requested model/revision;
- requested reasoning is declared by the profile;
- installation, adapter, protocol, recipe and Full Workspace identities agree;
- actor, execution-mode, feature, containment and workspace policy permit it.

Persisted provider model metadata is not admission authority. UI state is not
admission authority.

## Codex

Codex uses the `codex-app-server` native contract. Its model profile revision is
content-addressed from the current catalog model identity and reasoning choices.
Adapter identity is derived from declared engine/adapter ids and versions rather
than mutable source-file bytes.

Consequently, an ordinary Codex update or newly advertised model cannot disable
the runtime for lack of a renewed Maverick artifact. Current installation health,
catalog reconciliation, profile binding and live policy remain authoritative.

## Existing sessions and continuation

An existing session retains its immutable execution binding. Every turn still
revalidates live workspace, actor, health, model and policy authority.

A compatible profile/binding evolution may fork a continuation child only after
Core proves non-expansion, fences the predecessor, snapshots required private
state and transfers provider-thread ownership. It never rewrites a predecessor.
An incompatible change requires a new conversation or explicit transcript
handoff.

Runtime disablement, removed models, missing provider threads and failed
non-expansion proofs fail closed with public reason codes. They are not repaired
by changing a validity date.
