# Native admission and historical text sessions

P5 readiness is server authority, not just UI presentation. New agentic pins
must pass the same family/Full Workspace readiness check as Chat and Settings.
Explicitly restricted workspace policies are never widened to make this gate
pass: a partial agent remains unavailable. Existing immutable session pins are
not rewritten by this admission change.

Catalog reconciliation is not an operator enable action. A later disabled
successor is a tombstone for its binding lineage, including when its policy was
edited or the catalog subsequently advertises another revision. Independent
bindings with different authority remain independent. Only an explicit operator
reenable can supersede the disabled decision.

Historical `plain_hosted_chat` sessions without `hosted_text_binding` remain
readable but fail dispatch with `hosted_text_legacy_binding_required`, before
routing, credential access, or transport. Users must explicitly create a new
pinned conversation; today's provider, upstream, or retention policy is never
inferred retroactively for old messages.

The native connection certificate is composite: its immutable
`native_runtime_artifact` component pins the approved executable content hash
and version, references the connection, and shares its evidence, issuance, and
expiry. Both statuses are checked. Codex's one-time adoption uses the explicitly
reviewed `codex-cli 0.153.4` artifact, not whichever executable discovery happens
to find. Its actual standalone executable is resolved by the same command
resolver as launch; changing the shim is irrelevant if it is not executed.
Artifact replacement closes admission, live authority, launch, and resume. It
does not manufacture a fresh certificate, test run, or validity window. The
existing revision-14 Python bundle and immutable session/profile records stay
unchanged. A runtime upgrade requires an explicitly approved artifact release.

Exact model metadata is retained, but the current native transports select
aliases only. They reject `native_agent_exact_revision_unsupported` at admission,
certificate validation, launch, connect, execute, and resume. Previously persisted
exact pins also fail closed: matching a discovery snapshot cannot substitute
for a revision selector that the transport does not implement.
