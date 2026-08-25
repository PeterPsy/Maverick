"""Split tests from tests.support.cases.provider_cases.ProvidersTestCase."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from core.providers.errors import ProviderLaunchError
from core.providers.provider_codex_runtime import CodexProviderAdapter
from tests.support.cases import provider_cases as cases


_SELECTED = {
    'test_codex_runtime_home_is_prepared_from_configured_source_home',
    'test_codex_runtime_home_ignores_unreadable_source_config',
    'test_existing_runtime_maverick_wrapper_is_refreshed',
    'test_launch_spec_receives_provider_secret_via_platform_delivery',
}


def _mask_unselected(cls) -> None:
    for name in dir(cases.ProvidersTestCase):
        if name.startswith("test_") and name not in _SELECTED:
            setattr(cls, name, None)


class ProviderRuntimeHomeAndSecretsTest(cases.ProvidersTestCase):
    """Run the ProviderRuntimeHomeAndSecretsTest subset."""

    pass


_mask_unselected(ProviderRuntimeHomeAndSecretsTest)


class CodexContinuationRuntimeHomeTest(unittest.TestCase):
    def test_continuation_successor_reuses_lineage_root_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sessions_root = Path(temp_dir) / "runtime" / "sessions"
            lineage_root = sessions_root / "session-origin"
            predecessor_root = sessions_root / "session-predecessor"
            successor_root = sessions_root / "session-successor"
            lineage_home = lineage_root / "codex-home"
            lineage_home.mkdir(parents=True)
            (predecessor_root / "codex-home").mkdir(parents=True)
            successor_root.mkdir(parents=True)
            session = SimpleNamespace(
                session_id="session-successor",
                runtime_root=str(successor_root),
                predecessor_session_id="session-predecessor",
                lineage_root_session_id="session-origin",
                continuation_handoff_id="handoff-1",
            )

            runtime_home = CodexProviderAdapter()._runtime_home(session)
            command = CodexProviderAdapter()._build_command(
                workspace_root=Path(temp_dir),
                runtime_root=successor_root,
                runtime_home=runtime_home,
                execution_mode="sandbox",
                host_command="/bin/echo",
            )

            self.assertEqual(runtime_home, lineage_home)
            home_index = command.index("--home")
            self.assertEqual(command[home_index + 1], str(lineage_home))

    def test_continuation_runtime_home_fails_closed_when_lineage_root_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            successor_root = Path(temp_dir) / "runtime" / "sessions" / "session-successor"
            successor_root.mkdir(parents=True)
            session = SimpleNamespace(
                session_id="session-successor",
                runtime_root=str(successor_root),
                predecessor_session_id="session-predecessor",
                lineage_root_session_id="session-predecessor",
                continuation_handoff_id="handoff-1",
            )

            with self.assertRaisesRegex(
                ProviderLaunchError,
                "codex_continuation_runtime_home_missing",
            ):
                CodexProviderAdapter()._runtime_home(session)

    def test_partial_continuation_identity_never_falls_back_to_a_new_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            successor_root = Path(temp_dir) / "runtime" / "sessions" / "session-successor"
            successor_root.mkdir(parents=True)
            session = SimpleNamespace(
                session_id="session-successor",
                runtime_root=str(successor_root),
                predecessor_session_id="session-predecessor",
                lineage_root_session_id=None,
                continuation_handoff_id="handoff-1",
            )

            with self.assertRaisesRegex(
                ProviderLaunchError,
                "codex_continuation_runtime_home_unsafe",
            ):
                CodexProviderAdapter()._runtime_home(session)
