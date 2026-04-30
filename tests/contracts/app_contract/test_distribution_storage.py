"""Split tests from tests.support.cases.app_contract_cases.AppContractTestCase."""

from __future__ import annotations

from tests.support.cases import app_contract_cases as cases


_SELECTED = {
    'test_parse_contract_supports_source_available_distribution',
    'test_parse_contract_rejects_invalid_distribution_policy',
    'test_parse_contract_rejects_unknown_distribution_fields',
    'test_parse_contract_rejects_storage_outside_owned_namespace',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AppContractTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppContractDistributionStorageTest(cases.AppContractTestCase):
    """Run the AppContractDistributionStorageTest subset."""

    pass


_mask_unselected(AppContractDistributionStorageTest)
