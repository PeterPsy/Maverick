# Native Agent Admission

Native agent admission uses the installed runtime, its current model catalog and
the workspace's direct model configuration. It has no certificate, rollout
revision, profile lineage or renewal cycle.

## Installation contract

A native installation declares the runtime engine, adapter/version, structured
protocol, process-launch settings and effect mapping needed to run it. Those
fields describe executable integration code; they are not signed model
authority and are not copied into workspace or session identity metadata.

The model catalog is refreshed for discovery. A successful refresh replaces the
current list. A transient refresh failure retains the last usable snapshot and
does not expire an otherwise working Codex installation.

## New sessions

Core admits a native session when:

- an enabled workspace config selects the provider and model;
- the runtime is installed and healthy;
- the model and requested reasoning effort are supported;
- actor policy and execution mode allow the session.

Core then stores only the concrete inputs needed to continue that session:
workspace config id, runtime/adapter, provider/model/protocol, reasoning,
capabilities, route, credential reference, execution mode, policy, egress and
context/model settings.

## Codex

Codex uses the `codex-app-server` native integration. Each currently advertised
model has one stable direct config. Reconciliation updates that config in place;
it does not publish historical revisions. Discovery failure keeps the last
working catalog instead of turning a short refresh outage into model expiry.

## Existing sessions

Every turn rechecks only mutable authority that can actually change: the
workspace config remains enabled, the actor is allowed, credentials and runtime
health are available, the execution mode has not broadened, and tool/egress
policy still permits the operation.

If the session's concrete runtime inputs are no longer executable, Core returns
`runtime_session_restart_required`. It does not create continuation children,
lineage records, compatibility forks or provider snapshots. Starting a new
conversation is the explicit recovery path for an incompatible configuration.
