"""Phase 1-3A acceptance metadata for Website Studio."""

from __future__ import annotations


def phase_1_3a_acceptance_verification() -> dict[str, object]:
    """Return the implemented verification boundary exposed by the manifest."""
    return {
        "scope": "phase_1_phase_2_phase_3_app_orchestration_phase_3a_runtime_preview",
        "status": "implemented_with_guarded_platform_gaps",
        "automated_smoke_scenarios": [
            {
                "id": "static_zip_import_publish_rollback",
                "status": "required",
                "test": "apps/website-studio/tests/test_phase_acceptance_smoke.py::WebsiteStudioPhaseAcceptanceSmokeTest.test_static_zip_import_preview_publish_and_rollback_smoke",
                "covers": [
                    "zip_import",
                    "storage_artifact_reference",
                    "preview_document",
                    "preview_report",
                    "expected_hash_write",
                    "diff",
                    "publish_request",
                    "approval",
                    "managed_static_publish",
                    "rollback",
                ],
            },
            {
                "id": "node_build_local_npm_runtime",
                "status": "required",
                "test": "apps/website-studio/tests/test_phase_acceptance_smoke.py::WebsiteStudioPhaseAcceptanceSmokeTest.test_node_build_uses_real_npm_ci_and_runtime_artifact_smoke",
                "covers": [
                    "package_lock_required",
                    "npm_ci_ignore_scripts",
                    "site_local_build_binary",
                    "runtime_artifact",
                    "rendered_route_index",
                    "runtime_preview_document",
                ],
            },
            {
                "id": "php_runtime_preview",
                "status": "required_when_php_available",
                "test": "apps/website-studio/tests/test_phase_acceptance_smoke.py::WebsiteStudioPhaseAcceptanceSmokeTest.test_php_runtime_smoke_when_host_php_is_available",
                "covers": [
                    "php_loopback_preview",
                    "runtime_health",
                    "missing_php_blocks_closed",
                ],
            },
        ],
        "optional_external_smoke_scenarios": [
            {
                "id": "github_pull_request_live",
                "status": "manual_opt_in",
                "env": [
                    "WEBSITE_STUDIO_LIVE_GITHUB_REPO",
                    "WEBSITE_STUDIO_LIVE_GITHUB_TOKEN",
                    "WEBSITE_STUDIO_LIVE_GITHUB_CONFIRM=create_pr",
                ],
                "test": "apps/website-studio/tests/test_phase_acceptance_smoke.py::WebsiteStudioExternalAcceptanceSmokeTest.test_optional_live_github_pull_request_smoke",
                "side_effects": "creates or reuses a Website Studio branch and pull request in the configured sandbox repository",
            },
            {
                "id": "storage_zip_cli_round_trip",
                "status": "manual_opt_in",
                "env": ["WEBSITE_STUDIO_STORAGE_CLI_SMOKE=1"],
                "test": "apps/website-studio/tests/test_phase_acceptance_smoke.py::WebsiteStudioExternalAcceptanceSmokeTest.test_optional_storage_cli_zip_round_trip_smoke",
                "side_effects": "writes one generated Storage ZIP artifact through official Storage MCP surfaces",
            },
        ],
        "runtime_security_boundary": {
            "production_sandbox": False,
            "purpose": "workspace_preview_only",
            "app_owned_controls": [
                "path_checked_source_roots",
                "zip_and_source_tree_validation",
                "allowlisted_node_build_commands",
                "npm_ci_ignore_scripts",
                "site_local_build_binaries_only",
                "isolated_runtime_home_and_tmpdir",
                "bounded_subprocess_timeouts",
                "posix_process_group_cleanup",
                "best_effort_posix_resource_limits",
                "php_loopback_only",
                "opaque_origin_preview_iframe",
                "bounded_redacted_logs",
            ],
            "platform_gaps": [
                "os_level_sandboxing",
                "network_namespace_isolation",
                "production_secret_backend",
                "public_hosting_binding",
            ],
        },
        "scope_exclusions": [
            "public_custom_domain_provisioning",
            "certificate_issuance",
            "cdn_cache_enforcement",
            "public_production_binding",
            "long_running_production_runtime_hosting",
            "cms_connectors",
            "commerce_connectors",
            "external_deployment_writeback",
        ],
    }
