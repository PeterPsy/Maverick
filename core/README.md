# Maverick Core

This tree is the package root of the Maverick core.

The target architecture is defined in:

- `docs/architecture/core_architecture.md`

The core is organized by domain, not by legacy buckets.

Repository rules for this tree:

- core code lives directly under `core/`
- do not add wrapper folders such as `backend/`, `runtime_backend/`, or `app/`
- do not add an ambiguous `core/core/` subtree
- if shared internal helpers are needed, use a clearer package name such as `shared/`

Each domain should prefer small files with explicit names.

Agentic Phase-1 security ownership is also Core-local: workspace attestation is
an actor-attributed/revocable CAS record; exact resource classification and
per-block egress remain separate; canonical provenance/trust/data-class joins
fail closed; only certified Core-owned public schemas may reach a remote
request; and filesystem read/list/write/shell-cwd operations use pinned,
descriptor-relative workspace confinement. One effective capability snapshot
intersects certificate, profile, workspace, actor, live authority, flags, and
health for admission, continuation, request/catalog construction, API, Chat,
and Settings. Remote certificates bind the single deterministic manifest in
`core/providers/certified_execution_tcb.py`; drift invalidates authority.
Browser inputs and projections never carry classification or credential
authority. Exact Codex and `plain_hosted_chat` keep their existing paths, while
remote agentic availability remains false and NO-GO.
