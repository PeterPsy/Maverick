"""Split tests from tests.support.cases.provider_cases.ProvidersTestCase."""

from __future__ import annotations

from tests.support.cases import provider_cases as cases


_SELECTED = {
    'test_builtin_registry_registers_codex_provider',
    'test_application_bootstrap_registers_builtin_providers',
    'test_workspace_selection_requires_explicit_provider_configuration',
    'test_configured_selection_is_persisted_per_workspace',
    'test_bindings_store_secret_refs_without_raw_secret_values',
    'test_selection_requires_binding_for_credentialed_runtime_provider',
    'test_disable_binding_preserves_record_but_makes_it_inactive',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.ProvidersTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class ProviderRegistrySelectionTest(cases.ProvidersTestCase):
    """Run the ProviderRegistrySelectionTest subset."""

    pass


_mask_unselected(ProviderRegistrySelectionTest)
