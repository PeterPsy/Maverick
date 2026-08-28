"""Tests for exact sidecar route templates and path canonicalization."""

from __future__ import annotations

import unittest

from core.apps.models import HttpSidecarRoutePolicy, HttpSidecarRouteRule
from core.apps.sidecar_route_policy import (
    canonicalize_sidecar_path,
    route_policy_mode,
    route_rule_matches,
    validate_asgi_raw_path,
    validate_route_template,
)


def _rule(
    method: str | None,
    path_template: str,
    *,
    static_tree: bool = False,
) -> HttpSidecarRouteRule:
    return HttpSidecarRouteRule(
        method=method,
        path_template=path_template,
        static_tree=static_tree,
    )


class SidecarRoutePolicyTestCase(unittest.TestCase):
    def test_exact_templates_limit_parameters_to_one_segment(self) -> None:
        project = _rule("GET", "/api/projects/{project_id}")

        self.assertTrue(route_rule_matches(project, method="GET", path="/api/projects/project-a"))
        self.assertTrue(route_rule_matches(project, method="HEAD", path="/api/projects/project-a"))
        self.assertFalse(route_rule_matches(project, method="POST", path="/api/projects/project-a"))
        self.assertFalse(route_rule_matches(project, method="GET", path="/api/projects/project-a/terminals"))
        self.assertFalse(route_rule_matches(project, method="GET", path="/api/projects/a/b"))

    def test_named_splat_matches_one_or_more_segments_inside_an_exact_template(self) -> None:
        raw_file = _rule("GET", "/api/projects/{project_id}/raw/{*project_path}")
        version = _rule(
            "GET",
            "/api/projects/{project_id}/files/{*project_path}/versions/{version_id}",
        )

        self.assertTrue(
            route_rule_matches(raw_file, method="GET", path="/api/projects/p1/raw/index.html")
        )
        self.assertTrue(
            route_rule_matches(raw_file, method="GET", path="/api/projects/p1/raw/src/app.tsx")
        )
        self.assertFalse(route_rule_matches(raw_file, method="GET", path="/api/projects/p1/raw"))
        self.assertTrue(
            route_rule_matches(
                version,
                method="GET",
                path="/api/projects/p1/files/src/app.tsx/versions/v2",
            )
        )
        self.assertFalse(
            route_rule_matches(
                version,
                method="GET",
                path="/api/projects/p1/files/versions/v2",
            )
        )

        self.assertEqual(
            validate_route_template(raw_file.path_template, static_tree=False),
            raw_file.path_template,
        )

    def test_blocked_precedes_core_and_passthrough_and_unknown_is_denied(self) -> None:
        same = "/api/projects/{project_id}/danger"
        policy = HttpSidecarRoutePolicy(
            pass_through=[_rule("POST", same)],
            handled_by_core=[_rule("POST", same)],
            blocked=[_rule("POST", same)],
        )

        self.assertEqual(
            route_policy_mode(policy, method="POST", path="/api/projects/p1/danger"),
            "blocked",
        )
        self.assertEqual(
            route_policy_mode(policy, method="GET", path="/api/projects/p1/unknown"),
            "not_allowed",
        )

    def test_static_tree_is_explicit_safe_and_outside_api(self) -> None:
        rule = _rule("GET", "/_next", static_tree=True)

        self.assertTrue(route_rule_matches(rule, method="GET", path="/_next/static/build/app.js"))
        self.assertFalse(route_rule_matches(rule, method="POST", path="/_next/static/build/app.js"))
        self.assertEqual(validate_route_template("/_next", static_tree=True), "/_next")
        for invalid in ("/", "/api", "/api/assets", "/_next/{path}"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_route_template(invalid, static_tree=True)

    def test_template_validation_rejects_unsafe_splats_and_partial_parameters(self) -> None:
        for invalid in (
            "/api/projects/{*}",
            "/api/projects/{*path}/{*rest}",
            "/api/projects/{path}/{*path}",
            "/api/projects/:id",
            "/api/projects/{id}.json",
            "/api/projects/(.*)",
            "/api/projects/{id}/{id}",
            "/api/projects/",
            "/api//projects",
            "/api/%70rojects",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_route_template(invalid, static_tree=False)

    def test_canonicalization_rejects_traversal_empty_backslash_and_double_encoding(self) -> None:
        self.assertEqual(canonicalize_sidecar_path("api/projects/project-a"), "/api/projects/project-a")
        self.assertEqual(canonicalize_sidecar_path("/api/projects/project-a/"), "/api/projects/project-a")
        for invalid in (
            "api/projects/../secrets",
            "api//projects",
            "api\\projects",
            "api/projects/%2fsecrets",
            "//api/projects",
            "api/projects/\x00",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                canonicalize_sidecar_path(invalid)

        validate_asgi_raw_path(path="/api/projects/a b", raw_path=b"/api/projects/a%20b")
        for raw in (
            b"/api/projects/a%2fb",
            b"/api/projects/%2e%2e/secrets",
            b"/api/projects/%252fsecrets",
            b"/api/projects/%5csecrets",
            b"/api/projects/%zz",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_asgi_raw_path(path="/api/projects/decoded", raw_path=raw)


if __name__ == "__main__":
    unittest.main()
