"""Atomic cancellation proofs at model API and CLI submission boundaries."""

from __future__ import annotations

from pathlib import Path
import tempfile
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.model_access.api_proxy import ModelApiProxy, OpenRouterHttpTransport
from core.model_access.cancellation import (
    ModelAccessCancellation,
    ModelAccessRequestCancelled,
)
from core.model_access.cli_proxy import CodexCliExecutor
from core.model_access.models import ModelAccessScope, ProviderHttpResponse


class _RecordingTransport:
    def __init__(self) -> None:
        self.opened = False
        self.closed = Event()

    def open(self, **_kwargs) -> ProviderHttpResponse:
        self.opened = True
        return ProviderHttpResponse(
            status=200,
            headers=(),
            chunks=(),
            close=self.closed.set,
        )


class ModelAccessCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data_root = self.root / "data"
        self.data_root.mkdir()
        self.scope = ModelAccessScope(
            workspace_id="default",
            app_id="design-studio",
            sidecar_id="opendesign",
            data_root=self.data_root,
            api=True,
            cli=("codex",),
        )

    def test_revoked_api_request_is_fenced_before_transport_open(self) -> None:
        transport = _RecordingTransport()
        cancellation = Event()
        cancellation.set()

        with self.assertRaises(ModelAccessRequestCancelled):
            ModelApiProxy(object(), transport=transport).open_chat_completion(
                scope=self.scope,
                body=b'{"model":"model/exact","messages":[]}',
                cancellation=cancellation,
            )

        self.assertFalse(transport.opened)

    def test_cancellation_closes_a_submitted_api_response_immediately(self) -> None:
        transport = _RecordingTransport()
        cancellation = ModelAccessCancellation()
        proxy = ModelApiProxy(object(), transport=transport)
        catalog = SimpleNamespace(
            api_models=(
                SimpleNamespace(
                    available=True,
                    model_id="model/exact",
                    provider_id="openrouter",
                ),
            ),
        )
        with (
            patch("core.model_access.api_proxy.build_model_access_catalog", return_value=catalog),
            patch.object(proxy, "_credential", return_value="secret"),
        ):
            response = proxy.open_chat_completion(
                scope=self.scope,
                body=b'{"model":"model/exact","messages":[]}',
                cancellation=cancellation,
            )

        cancellation.set()

        self.assertTrue(transport.closed.wait(1))
        response.close()

    def test_revocation_between_connection_creation_and_submit_sends_nothing(self) -> None:
        cancellation = ModelAccessCancellation()
        connection = Mock()
        connection.sock = None

        def create_connection(*_args, **_kwargs):
            cancellation.set()
            return connection

        with patch(
            "core.model_access.api_proxy.http.client.HTTPSConnection",
            side_effect=create_connection,
        ):
            with self.assertRaises(ModelAccessRequestCancelled):
                OpenRouterHttpTransport().open(
                    provider_id="openrouter",
                    body=b"{}",
                    credential="secret",
                    cancellation=cancellation,
                )

        connection.request.assert_not_called()
        connection.close.assert_called_once()

    def test_submission_fence_linearizes_registration_and_revocation(self) -> None:
        cancellation = ModelAccessCancellation()
        resource_registered = Event()
        finish_submission = Event()
        cleanup_called = Event()
        revocation_finished = Event()

        def submit() -> None:
            with cancellation.submission_fence():
                cancellation.register_cleanup(cleanup_called.set)
                resource_registered.set()
                finish_submission.wait(1)

        def revoke() -> None:
            cancellation.set()
            revocation_finished.set()

        submitter = Thread(target=submit)
        submitter.start()
        self.assertTrue(resource_registered.wait(1))
        revoker = Thread(target=revoke)
        revoker.start()
        self.assertFalse(revocation_finished.wait(0.05))
        finish_submission.set()
        submitter.join(timeout=1)
        revoker.join(timeout=1)

        self.assertFalse(submitter.is_alive())
        self.assertFalse(revoker.is_alive())
        self.assertTrue(cleanup_called.is_set())
        self.assertTrue(revocation_finished.is_set())

    def test_revoked_cli_request_is_fenced_before_process_spawn(self) -> None:
        cancellation = Event()
        cancellation.set()
        executor = CodexCliExecutor(repository_root=self.root)

        with patch("core.model_access.cli_proxy.subprocess.Popen") as spawn:
            with self.assertRaises(ModelAccessRequestCancelled):
                list(
                    executor.execute(
                        scope=self.scope,
                        provider_id="codex",
                        argv=("--version",),
                        cwd="/app",
                        stdin=b"",
                        cancellation=cancellation,
                    )
                )

        spawn.assert_not_called()

    def test_cli_revocation_during_spawn_terminates_the_new_process(self) -> None:
        cancellation = ModelAccessCancellation()
        executor = CodexCliExecutor(repository_root=self.root)
        process = Mock()
        process.poll.return_value = 0

        def spawn(*_args, **_kwargs):
            cancellation.set()
            return process

        with (
            patch("core.model_access.cli_proxy.resolve_codex_executable", return_value=Path("/codex")),
            patch("core.model_access.cli_proxy._prepare_codex_home", return_value=Path("/home")),
            patch("core.model_access.cli_proxy._codex_sandbox_command", return_value=["codex"]),
            patch("core.model_access.cli_proxy.subprocess.Popen", side_effect=spawn),
            patch("core.model_access.cli_proxy._cancel_process_group") as cancel_process,
        ):
            with self.assertRaises(ModelAccessRequestCancelled):
                list(
                    executor.execute(
                        scope=self.scope,
                        provider_id="codex",
                        argv=("--version",),
                        cwd="/app",
                        stdin=b"",
                        cancellation=cancellation,
                    )
                )

        cancel_process.assert_called_once_with(process)


if __name__ == "__main__":
    unittest.main()
