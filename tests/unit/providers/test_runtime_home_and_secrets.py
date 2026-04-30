"""Split tests from tests.support.cases.provider_cases.ProvidersTestCase."""

from __future__ import annotations

from tests.support.cases import provider_cases as cases


_SELECTED = {
    'test_codex_runtime_home_is_prepared_from_configured_source_home',
    'test_codex_runtime_home_ignores_unreadable_source_config',
    'test_existing_runtime_maverick_wrapper_is_refreshed',
    'test_launch_spec_receives_provider_secret_via_platform_delivery',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.ProvidersTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class ProviderRuntimeHomeAndSecretsTest(cases.ProvidersTestCase):
    """Run the ProviderRuntimeHomeAndSecretsTest subset."""

    pass


_mask_unselected(ProviderRuntimeHomeAndSecretsTest)
