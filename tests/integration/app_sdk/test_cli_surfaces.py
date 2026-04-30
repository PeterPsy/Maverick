"""Split tests from tests.support.cases.app_sdk_cases.MaverickAppSdkTestCase."""

from __future__ import annotations

from tests.support.cases import app_sdk_cases as cases


_SELECTED = {
    'test_sdk_cli_create_register_install_status_and_app_cli_surface',
    'test_status_distinguishes_source_registered_and_installed',
    'test_entity_sqlite_template_exercises_backend_cli_and_mcp',
    'test_cli_wrapper_creates_workspace_app',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.MaverickAppSdkTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppSdkCliSurfaceTest(cases.MaverickAppSdkTestCase):
    """Run the AppSdkCliSurfaceTest subset."""

    pass


_mask_unselected(AppSdkCliSurfaceTest)
