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
