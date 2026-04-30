"""Split tests from tests.support.cases.app_contract_cases.AppContractTestCase."""

from __future__ import annotations

from tests.support.cases import app_contract_cases as cases


_SELECTED = {
    'test_parse_contract_round_trips_widget_declarations',
    'test_parse_contract_rejects_duplicate_widget_ids',
    'test_parse_contract_rejects_unsafe_widget_mount',
    'test_parse_contract_rejects_widget_actions_without_surface',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.AppContractTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppContractWidgetTest(cases.AppContractTestCase):
    """Run the AppContractWidgetTest subset."""

    pass


_mask_unselected(AppContractWidgetTest)
