"""Split tests from tests.support.cases.app_contract_cases.AppContractTestCase."""

from __future__ import annotations

from tests.support.cases import app_contract_cases as cases


_SELECTED = {
    'test_parse_contract_file_supports_storage_capabilities_and_lifecycle',
    'test_parse_contract_rejects_unknown_root_and_section_fields',
    'test_parse_contract_rejects_invalid_operational_permissions',
    'test_parse_contract_rejects_invalid_required_interface_metadata',
    'test_parse_contract_rejects_invalid_provided_interface_surface',
    'test_parse_contract_rejects_invalid_reference_entity_metadata',
    'test_parse_contract_rejects_missing_contract_file',
    'test_parse_contract_rejects_non_canonical_app_id',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AppContractTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppContractParserTest(cases.AppContractTestCase):
    """Run the AppContractParserTest subset."""

    pass


_mask_unselected(AppContractParserTest)
