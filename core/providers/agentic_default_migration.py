"""One-way adoption of legacy defaults; explicit agentic bindings take priority."""

from dataclasses import replace

from core.providers.agentic_profiles import _default_workspace_binding_id, ensure_codex_workspace_profile
from core.providers.models import ProviderSelection


def migrate_legacy_codex_defaults(store, registry, *, now):
    codex = registry.get_provider_definition("codex")
    models = {item.model_id for item in codex.model_options}
    for selection in store.list_provider_selections():
        if selection.provider_id != "codex":
            continue
        bindings = store.list_workspace_agentic_profile_bindings(selection.workspace_id)
        if bindings:
            _demote_duplicate_legacy_default(store, selection.workspace_id, bindings, now=now)
            # Legacy ProviderSelection is not a fresh enable/default decision.
            # Profile upgrades are handled by catalog reconciliation instead.
            continue
        if selection.model_id in models:
            ensure_codex_workspace_profile(store, definition=codex, selection=selection, now=now)

    if not store.list_workspace_agentic_profile_bindings("default") and codex.model_options:
        ensure_codex_workspace_profile(
            store, definition=codex, now=now,
            selection=ProviderSelection(
                selection_id="agentic-bootstrap:default:codex", workspace_id="default",
                provider_id="codex", binding_id=None, selection_scope="workspace_default",
                selection_reason="agentic schema bootstrap default", created_at=now, updated_at=now,
                model_id=codex.default_model_family, model_reasoning_effort=None,
            ),
        )


def _demote_duplicate_legacy_default(store, workspace_id, bindings, *, now):
    """Repair the old bootstrap's extra default, without changing any authority."""
    defaults = [binding for binding in bindings if binding.enabled and binding.is_default]
    legacy_id = _default_workspace_binding_id(workspace_id)
    if len(defaults) <= 1:
        return
    for binding in defaults:
        if binding.binding_id == legacy_id:
            store.save_workspace_agentic_profile_binding(
                replace(binding, is_default=False, revision=binding.revision + 1, updated_at=now),
                expected_revision=binding.revision,
            )
            # Do not choose between conflicting explicit operator defaults.
            # Those remain ambiguous and require an explicit operator decision.
            return


__all__ = ["migrate_legacy_codex_defaults"]
