"""Split tests from tests.support.cases.app_contract_cases.AppContractTestCase."""

from __future__ import annotations

from tests.support.cases import app_contract_cases as cases


_SELECTED = {
    'test_run_lifecycle_hook_uses_configured_timeout_mapping',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AppContractTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppContractLifecycleHookTest(cases.AppContractTestCase):
    """Run the AppContractLifecycleHookTest subset."""

    pass


_mask_unselected(AppContractLifecycleHookTest)
