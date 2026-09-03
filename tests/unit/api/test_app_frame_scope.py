"""Tests for app-frame owner authority propagated through internal scopes."""

from __future__ import annotations

import unittest

from core.api.app_frame_scope import (
    APP_FRAME_APP_ID_SCOPE_KEY,
    APP_FRAME_MOUNT_APP_ID_SCOPE_KEY,
    APP_FRAME_PROXY_SCOPE_KEY,
    app_frame_owner_matches,
    app_frame_path_matches_owner,
    bind_app_frame_scope,
    copy_app_frame_scope_to_environ,
)


class AppFrameScopeTests(unittest.TestCase):
    def test_binding_overwrites_untrusted_scope_values_and_reaches_wsgi(self) -> None:
        bound = bind_app_frame_scope(
            {
                APP_FRAME_PROXY_SCOPE_KEY: False,
                APP_FRAME_APP_ID_SCOPE_KEY: "attacker",
                APP_FRAME_MOUNT_APP_ID_SCOPE_KEY: "attacker-mount",
            },
            app_id="notes-local",
            mount_app_id="notes-mount",
        )
        environ: dict[str, object] = {}

        copy_app_frame_scope_to_environ(bound, environ)

        self.assertIs(environ[APP_FRAME_PROXY_SCOPE_KEY], True)
        self.assertEqual(environ[APP_FRAME_APP_ID_SCOPE_KEY], "notes-local")
        self.assertEqual(environ[APP_FRAME_MOUNT_APP_ID_SCOPE_KEY], "notes-mount")
        self.assertTrue(app_frame_owner_matches(environ, "notes-local"))
        self.assertTrue(app_frame_owner_matches(environ, "notes-mount"))
        self.assertFalse(app_frame_owner_matches(environ, "other-app"))

    def test_proxy_marker_without_a_bound_owner_fails_closed(self) -> None:
        self.assertFalse(
            app_frame_owner_matches({APP_FRAME_PROXY_SCOPE_KEY: True}, "notes")
        )

    def test_app_and_widget_paths_must_match_the_bound_owner(self) -> None:
        for path in (
            "/apps/other-app/",
            "/apps/other-app/assets/main.js",
            "/api/apps/widgets/other-app/sidebar/frontend/",
        ):
            with self.subTest(path=path):
                self.assertFalse(
                    app_frame_path_matches_owner(
                        path,
                        app_id="notes-local",
                        mount_app_id="notes-mount",
                    )
                )
        self.assertTrue(
            app_frame_path_matches_owner(
                "/apps/notes-mount/",
                app_id="notes-local",
                mount_app_id="notes-mount",
            )
        )
        self.assertTrue(
            app_frame_path_matches_owner(
                "/api/session",
                app_id="notes-local",
                mount_app_id="notes-mount",
            )
        )

    def test_unicode_app_and_widget_owners_fail_closed(self) -> None:
        bound = bind_app_frame_scope(
            {},
            app_id="notes-local",
            mount_app_id="notes-mount",
        )
        self.assertFalse(app_frame_owner_matches(bound, "é"))

        for path in (
            "/apps/é/",
            "/api/apps/widgets/é/sidebar/frontend/",
        ):
            with self.subTest(path=path):
                self.assertFalse(
                    app_frame_path_matches_owner(
                        path,
                        app_id="notes-local",
                        mount_app_id="notes-mount",
                    )
                )


if __name__ == "__main__":
    unittest.main()
