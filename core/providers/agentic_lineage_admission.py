"""Admission-only lineage governance, separate from existing pinned authority."""

from dataclasses import replace
import hashlib

from core.providers.errors import AgenticProfileError
from core.runtime.execution_binding import canonical_digest


def binding_authority_digest(binding):
    return canonical_digest({
        "credential_binding_id": binding.credential_binding_id,
        "actor_policy": binding.actor_policy,
        "workspace_policy_ceiling": binding.workspace_policy_ceiling,
        "egress_policy_id": binding.egress_policy_id,
        "egress_policy_revision": binding.egress_policy_revision,
    })


def rolled_binding_id(source, target_revision):
    digest = hashlib.sha256((
        f"{source.workspace_id}\0{source.definition_id}\0{target_revision}\0"
        f"{binding_authority_digest(source)}"
    ).encode("utf-8")).hexdigest()[:20]
    return f"workspace-agentic-rollforward-{digest}"


def lineage_members(source, bindings):
    """Recover old deterministic ancestry and retain links across policy edits."""
    candidates = {item.binding_id: item for item in bindings
                  if item.workspace_id == source.workspace_id and item.definition_id == source.definition_id}
    candidates[source.binding_id] = source
    members = {source.binding_id: source}
    pending = [source]
    while pending:
        current = pending.pop()
        current_ids = {current.binding_id, *current.lineage_binding_ids}
        for item in candidates.values():
            if item.binding_id in members:
                continue
            if (
                current_ids.intersection((item.binding_id, *item.lineage_binding_ids))
                or binding_authority_digest(current) == binding_authority_digest(item)
                or item.binding_id == rolled_binding_id(current, item.definition_revision)
                or current.binding_id == rolled_binding_id(item, current.definition_revision)
            ):
                members[item.binding_id] = item
                pending.append(item)
    return tuple(members.values())


def lineage_admission_disabled(source, bindings):
    # Fast path also keeps non-native/readiness fixtures without ancestry cheap.
    if not any(not item.enabled or item.admission_disabled_at is not None for item in bindings):
        return False
    members = lineage_members(source, bindings)
    disabled = [item.admission_disabled_at or item.updated_at for item in members
                if not item.enabled or item.admission_disabled_at is not None]
    enabled = [item.admission_enabled_at for item in members if item.admission_enabled_at is not None]
    return bool(disabled and (not enabled or max(disabled) >= max(enabled)))


def require_lineage_admission(store, binding):
    if binding is None:
        return
    # Readiness can also receive a pinned projection; never trust its old policy
    # as the mutable workspace admission state.
    if not hasattr(binding, "binding_id"):
        binding = store.get_workspace_agentic_profile_binding(binding.workspace_binding_id)
    bindings = store.list_workspace_agentic_profile_bindings(binding.workspace_id)
    if lineage_admission_disabled(binding, bindings):
        raise AgenticProfileError("workspace_profile_lineage_disabled")


def record_lineage_decision(desired, existing, bindings, *, operator_decision, now):
    # Discover ancestry before a policy/credential edit changes authority hashes.
    members = lineage_members(existing or desired, bindings)
    ids = {desired.binding_id, *(item.binding_id for item in members)}
    for item in members:
        ids.update(item.lineage_binding_ids)
    enabled_at = None if existing is None else existing.admission_enabled_at
    disabled_at = None if existing is None else existing.admission_disabled_at
    if existing is not None and not existing.enabled and disabled_at is None:
        disabled_at = existing.updated_at
    if operator_decision and (existing is None or existing.enabled != desired.enabled):
        if desired.enabled:
            enabled_at = now
        else:
            disabled_at = now
    return replace(desired, lineage_binding_ids=tuple(sorted(ids)),
                   admission_enabled_at=enabled_at, admission_disabled_at=disabled_at)


__all__ = ["binding_authority_digest", "rolled_binding_id", "lineage_admission_disabled",
           "require_lineage_admission", "record_lineage_decision"]
