"""Security boundaries for Antigravity's cached OAuth runtime profile."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.providers.antigravity_cli_runtime_home import (
    ANTIGRAVITY_OAUTH_TOKEN_FILENAME,
    ANTIGRAVITY_PROFILE_RELATIVE_PATH,
    prepare_antigravity_runtime_home,
    resolve_antigravity_source_home,
    validate_antigravity_oauth_source,
)
from core.providers.native_structured_cli_transport import NativeStructuredCliError


class AntigravityCliRuntimeHomeTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.source = self.root / "operator-profile"
        self.source.mkdir(mode=0o700)
        self.token = self.source / ANTIGRAVITY_OAUTH_TOKEN_FILENAME
        self.token.write_text("synthetic-oauth-profile", encoding="utf-8")
        self.token.chmod(0o600)

    def test_copies_only_oauth_identity_and_owned_settings(self) -> None:
        home = prepare_antigravity_runtime_home(
            self.runtime,
            source_home=self.source,
        )

        profile = home / ANTIGRAVITY_PROFILE_RELATIVE_PATH
        copied = profile / ANTIGRAVITY_OAUTH_TOKEN_FILENAME
        settings = profile / "settings.json"
        self.assertEqual(copied.read_text(encoding="utf-8"), "synthetic-oauth-profile")
        self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
        self.assertEqual(home.stat().st_mode & 0o777, 0o700)
        self.assertEqual(
            json.loads(settings.read_text(encoding="utf-8")),
            {
                "enableTerminalSandbox": True,
                "toolPermission": "request-review",
            },
        )
        self.assertNotIn("modelProvider", settings.read_text(encoding="utf-8"))
        self.assertEqual(
            sorted(path.name for path in profile.iterdir()),
            [ANTIGRAVITY_OAUTH_TOKEN_FILENAME, "settings.json"],
        )

    def test_replaces_stale_runtime_material_without_following_symlinks(self) -> None:
        profile = (
            self.runtime
            / "antigravity-home"
            / ANTIGRAVITY_PROFILE_RELATIVE_PATH
        )
        profile.mkdir(parents=True)
        external = self.root / "external"
        external.write_text("untouched", encoding="utf-8")
        (profile / ANTIGRAVITY_OAUTH_TOKEN_FILENAME).symlink_to(external)
        (profile / "settings.json").symlink_to(external)

        prepare_antigravity_runtime_home(self.runtime, source_home=self.source)

        self.assertEqual(external.read_text(encoding="utf-8"), "untouched")
        self.assertFalse(
            (profile / ANTIGRAVITY_OAUTH_TOKEN_FILENAME).is_symlink()
        )
        self.assertFalse((profile / "settings.json").is_symlink())

    def test_missing_or_weak_oauth_material_fails_closed(self) -> None:
        cases = []
        missing = self.root / "missing"
        cases.append((missing, "oauth_credential_missing"))

        weak_home = self.root / "weak-home"
        weak_home.mkdir(mode=0o755)
        weak_token = weak_home / ANTIGRAVITY_OAUTH_TOKEN_FILENAME
        weak_token.write_text("token", encoding="utf-8")
        weak_token.chmod(0o600)
        cases.append((weak_home, "oauth_credential_invalid"))

        weak_token_home = self.root / "weak-token"
        weak_token_home.mkdir(mode=0o700)
        weak = weak_token_home / ANTIGRAVITY_OAUTH_TOKEN_FILENAME
        weak.write_text("token", encoding="utf-8")
        weak.chmod(0o644)
        cases.append((weak_token_home, "oauth_credential_invalid"))

        empty_home = self.root / "empty-token"
        empty_home.mkdir(mode=0o700)
        empty = empty_home / ANTIGRAVITY_OAUTH_TOKEN_FILENAME
        empty.touch(mode=0o600)
        cases.append((empty_home, "oauth_credential_invalid"))

        for source, reason in cases:
            with self.subTest(source=source.name):
                with self.assertRaisesRegex(NativeStructuredCliError, reason):
                    prepare_antigravity_runtime_home(
                        self.runtime,
                        source_home=source,
                    )

    def test_symlink_hardlink_and_runtime_source_are_rejected(self) -> None:
        symlink_home = self.root / "symlink-home"
        symlink_home.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "oauth_credential_invalid",
        ):
            prepare_antigravity_runtime_home(
                self.runtime,
                source_home=symlink_home,
            )

        linked_home = self.root / "linked-home"
        linked_home.mkdir(mode=0o700)
        os.link(
            self.token,
            linked_home / ANTIGRAVITY_OAUTH_TOKEN_FILENAME,
        )
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "oauth_credential_invalid",
        ):
            validate_antigravity_oauth_source(linked_home)

        token_symlink_home = self.root / "token-symlink-home"
        token_symlink_home.mkdir(mode=0o700)
        (token_symlink_home / ANTIGRAVITY_OAUTH_TOKEN_FILENAME).symlink_to(
            self.token
        )
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "oauth_credential_unavailable",
        ):
            validate_antigravity_oauth_source(token_symlink_home)

        runtime_source = self.runtime / "credential-source"
        runtime_source.mkdir(mode=0o700)
        runtime_token = runtime_source / ANTIGRAVITY_OAUTH_TOKEN_FILENAME
        runtime_token.write_text("token", encoding="utf-8")
        runtime_token.chmod(0o600)
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "oauth_credential_invalid",
        ):
            prepare_antigravity_runtime_home(
                self.runtime,
                source_home=runtime_source,
            )

    def test_environment_override_is_explicit_and_validated(self) -> None:
        with patch.dict(
            os.environ,
            {"MAVERICK_ANTIGRAVITY_HOME": str(self.source)},
        ):
            self.assertEqual(resolve_antigravity_source_home(), self.source)
            validate_antigravity_oauth_source()


if __name__ == "__main__":
    unittest.main()
