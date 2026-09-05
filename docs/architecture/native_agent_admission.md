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

The same lineage gate is enforced for new pins and native UI readiness, not
only when generating successors. A catalog rollback cannot restore admission
through an enabled predecessor. Ancestry is inferred for old records from the
shared authority and deterministic roll-forward ids; subsequent writes retain
`lineage_binding_ids` so policy/credential edits cannot sever those links.
Bindings record separate `admission_enabled_at`/`admission_disabled_at` decision
timestamps. Only an explicit enable/disable transition (or explicit binding
creation) advances them; reconciliation and default demotion never count as an
operator reenable. Legacy disabled records are conservative tombstones until a
new explicit enable supersedes them; disable wins equal timestamps. This gate
does not change certificates or existing immutable pins: already pinned sessions
retain their separate live binding/policy/certificate checks, without inheriting
another lineage member's admission-only disable.

Cold bootstrap follows the same rule: a legacy `ProviderSelection` is adopted
only if that workspace has no agentic bindings. It never reenables a disabled
binding or repromotes a demoted legacy default. For stores already affected by
the former bootstrap replay, migration clears only the deterministic legacy
binding's duplicate default flag when an explicit default is also present. It
retains that binding's enabled state, policies, credentials, and existing pins;
the explicit default is unchanged. Multiple explicit defaults remain ambiguous
and fail closed rather than being resolved by timestamp or list order.

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
