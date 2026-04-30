"""Split tests from tests.support.cases.app_sdk_cases.MaverickAppSdkTestCase."""

from __future__ import annotations

from tests.support.cases import app_sdk_cases as cases


_SELECTED = {
    'test_workspace_sdk_api_uses_runtime_token_without_default_workspace_fallback',
    'test_workspace_sdk_api_returns_documentation_content',
    'test_runtime_cli_api_runs_official_cli_with_runtime_token_workspace',
    'test_runtime_cli_api_runs_app_sdk_status_with_runtime_token_workspace',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.MaverickAppSdkTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class AppSdkRuntimeApiTest(cases.MaverickAppSdkTestCase):
    """Run the AppSdkRuntimeApiTest subset."""

    pass


_mask_unselected(AppSdkRuntimeApiTest)
