"""Split tests from tests.support.cases.app_sdk_cases.MaverickAppSdkTestCase."""

from __future__ import annotations

from tests.support.cases import app_sdk_cases as cases


_SELECTED = {
    'test_sdk_generates_valid_contracts_for_supported_templates',
    'test_storage_helpers_reject_path_traversal',
    'test_package_valid_app_source_excludes_generated_junk',
    'test_sdk_validation_enforces_reference_and_view_state_surface_completeness',
    'test_runtime_api_token_carries_mode_and_expires',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.MaverickAppSdkTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppSdkGenerationTest(cases.MaverickAppSdkTestCase):
    """Run the AppSdkGenerationTest subset."""

    pass


_mask_unselected(AppSdkGenerationTest)
