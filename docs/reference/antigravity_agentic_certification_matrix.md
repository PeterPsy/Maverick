# Antigravity Native Agent certification matrix

Revision: `2026-09-11-r62-openrouter-glm-5-3-flash-relace-tcb52`

This matrix certifies one `antigravity-cli` → `google` native connection, not
individual model slugs. Catalog slugs inherit the connection evidence through
immutable, content-addressed model projections. Catalog discovery, OAuth
readiness, or a successful process exit cannot create this authority.

## Immutable target

- Antigravity CLI runtime artifact: reviewed version `1.1.27` and its exact
  content digest from `native_runtime_artifact.py`.
- Adapter revision `5` and harness recipe revision `4`, structured persistent
  `stream-json`, machine-readable events, no terminal scraping.
- Authentication: a session-private copy of the operator-managed cached OAuth
  identity; no API key or workspace credential binding is accepted.
- Workspace boundary: outer Bubblewrap confinement, native workspace access
  read-only, writable private runtime state, and Core-governed mutations through
  the runtime-local `maverick` wrapper.
- Full Workspace contract: `codex-baseline-v20`, exact CLI/MCP/app/capability
  surfaces, explicit mutating/destructive confirmation, bounded context and
  safe-next-turn steering.

## Deterministic and live gates

The suite must run with zero skips from a clean exact commit. The live smoke
must observe the authenticated catalog and one real structured turn, including
init identity, at least one structured event, exact usage, one non-empty final,
and process cleanup. It reserves Google free-tier quota in the shared durable
P6 ledger before provider egress.
Same-session preparations are serialized across skill materialization, owner
selection, and connection; concurrent callers must share one preparation and
one supervised process.
Any prepare, execute, or close failure is reduced to a bounded stage-specific
reason without raw provider output. A close failure cannot replace an earlier
turn failure, and incomplete process cleanup is never accepted as success.

The live smoke is only protocol evidence. Before signing, the authorized
`autonomous_post_evidence_review` role must review all 14 executed scenarios defined in
`certification_behavior.py` under the `native_connection` scope, with the
`default` effort dimension, the exact source/TCB/target, bounded resources, and
all absolute failure counters at zero.

## Publication and release

`publish_antigravity_connection_certificate` accepts only the complete signed
suite-62 run from an already trusted Ed25519 signer and rechecks deployed
source, TCB, matrix, target, adapter bytes, and installed runtime artifact. A
valid root permits catalog projection but does not activate the provider or a
workspace binding. Provider activation is an explicit operator action; global
and Antigravity-specific kill switches, current workspace attestation, a
disposable canary, rollback rehearsal, and the autonomous post-evidence security
gate remain mandatory.

Suite 60 / TCB manifest 50 advances the native evidence identity because the
broad certified TCB now includes the hosted finalization-runway correction.
Antigravity adapter 5, native recipe 4, installed CLI artifact, OAuth boundary,
and native target digest are unchanged. Its earlier suite-59 live receipt
cannot be reused across the new TCB identity.
