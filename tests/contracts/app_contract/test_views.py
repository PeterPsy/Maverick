"""Split tests from tests.support.cases.app_contract_cases.AppContractTestCase."""

from __future__ import annotations

from tests.support.cases import app_contract_cases as cases


_SELECTED = {
    'test_parse_contract_rejects_view_surface_for_undeclared_entity_type',
    'test_parse_contract_rejects_view_surface_for_undeclared_view',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AppContractTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppContractViewSurfaceTest(cases.AppContractTestCase):
    """Run the AppContractViewSurfaceTest subset."""

    pass


_mask_unselected(AppContractViewSurfaceTest)
