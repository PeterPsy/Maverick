"""Split tests from tests.support.cases.provider_cases.ProvidersTestCase."""

from __future__ import annotations

from tests.support.cases import provider_cases as cases


_SELECTED = {
    'test_codex_launch_spec_is_built_from_provider_adapter_not_runtime_domain',
    'test_codex_nvm_dependency_root_is_standalone_binary_parent',
    'test_codex_nvm_dependency_root_fails_closed_without_standalone_binary',
    'test_codex_launch_bypasses_host_wrapper_that_clears_runtime_env',
    'test_codex_full_access_runtime_bin_prefers_vendored_rg_binary',
    'test_codex_skill_prepare_empty_set_cleans_previous_skills',
    'test_codex_skill_prepare_removes_stale_manifest_targets',
    'test_codex_skill_prepare_reuses_current_manifest',
    'test_codex_post_tool_use_hook_trust_identity_is_stable',
    'test_workspace_maverick_wrapper_exits_nonzero_for_error_status_payload',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.ProvidersTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class CodexLaunchSpecTest(cases.ProvidersTestCase):
    """Run the CodexLaunchSpecTest subset."""

    pass


_mask_unselected(CodexLaunchSpecTest)
