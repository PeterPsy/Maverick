"""Tests for the runtime-token CLI HTTP bridge."""

from __future__ import annotations

from contextlib import ExitStack
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api.orchestration_workers import resume_orchestrated_execution_worker
from core.api.runtime_cli_api import handle_runtime_cli_api


class RuntimeCliApiTest(unittest.TestCase):
    def test_runtime_cli_injects_hosted_orchestration_resume(self) -> None:
        state = self._state()

        with self._trusted_runtime():
            with patch(
                "core.api.runtime_cli_api.run_cli_json",
                return_value={"status_code": 200},
            ) as run_cli:
                status, _payload = self._invoke_runtime_cli(
                    state,
                    {"argv": ["core", "cli", "run", "inter-agent.runs.resume"]},
                )

        self.assertEqual(status, "200 OK")
        self.assertIs(
            run_cli.call_args.kwargs["orchestration_resume"],
            resume_orchestrated_execution_worker,
        )

    def test_runtime_cli_defaults_to_full_output(self) -> None:
        state = self._state()
        huge_output = "line\n" * 20_000

        with self._trusted_runtime():
            with patch(
                "core.api.runtime_cli_api.run_cli_json",
                return_value={"status_code": 200, "content": huge_output},
            ):
                status, payload = self._invoke_runtime_cli(state, {"argv": ["core", "cli", "run", "docs"]})

        self.assertEqual(status, "200 OK")
        self.assertEqual(payload["content"], huge_output)
        self.assertNotIn("output_compaction", payload)

    def test_runtime_cli_provider_compact_compacts_large_text_fields(self) -> None:
        state = self._state()
        huge_output = "Authorization: Bearer secret-token\n" + ("build cache entry\n" * 20_000)

        with self._trusted_runtime():
            with patch(
                "core.api.runtime_cli_api.run_cli_json",
                return_value={"status_code": 200, "content": huge_output},
            ):
                status, payload = self._invoke_runtime_cli(
                    state,
                    {"argv": ["core", "cli", "run", "docs"], "output_profile": "provider_compact"},
                )

        self.assertEqual(status, "200 OK")
        self.assertIn("[tool output compacted]", payload["content"])
        self.assertIn("scope: runtime_cli_response", payload["content"])
        self.assertNotIn("secret-token", payload["content"])
        self.assertEqual(payload["output_compaction"]["scope"], "runtime_cli_response")
        self.assertEqual(payload["output_compaction"]["output_profile"], "provider_compact")
        self.assertTrue(payload["output_compaction"]["applied"])
        self.assertEqual(payload["output_compaction"]["fields"], ["content"])
        self.assertEqual(payload["status_code"], 200)

    def test_runtime_cli_rejects_unknown_output_profile(self) -> None:
        state = self._state()

        with self._trusted_runtime():
            with patch("core.api.runtime_cli_api.run_cli_json") as run_cli:
                status, payload = self._invoke_runtime_cli(
                    state,
                    {"argv": ["apps", "list", "--json"], "output_profile": "compact_everything"},
                )

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["error"], "invalid_output_profile")
        run_cli.assert_not_called()

    def test_runtime_cli_provider_compact_preserves_error_http_status(self) -> None:
        state = self._state()
        huge_detail = "Traceback\n" + ("failure detail\n" * 20_000)

        with self._trusted_runtime():
            with patch(
                "core.api.runtime_cli_api.run_cli_json",
                return_value={"status_code": 400, "error": "unsupported", "detail": huge_detail},
            ):
                status, payload = self._invoke_runtime_cli(
                    state,
                    {"argv": ["core", "cli", "run", "missing"], "output_profile": "provider_compact"},
                )

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["status_code"], 400)
        self.assertEqual(payload["error"], "unsupported")
        self.assertIn("[tool output compacted]", payload["detail"])

    def test_runtime_cli_provider_compact_redacts_system_exit_detail(self) -> None:
        state = self._state()
        detail = "CLI failed with API_TOKEN=secret-value\n"

        with self._trusted_runtime():
            with patch("core.api.runtime_cli_api.run_cli_json", side_effect=SystemExit(detail)):
                status, payload = self._invoke_runtime_cli(
                    state,
                    {"argv": ["core", "cli", "run", "missing"], "output_profile": "provider_compact"},
                )

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["status_code"], 400)
        self.assertEqual(payload["error"], "cli_command_failed")
        self.assertIn("API_TOKEN=<redacted>", payload["detail"])
        self.assertNotIn("secret-value", payload["detail"])
        self.assertEqual(payload["output_compaction"]["fields"], ["detail"])
        self.assertEqual(payload["output_compaction"]["scope"], "runtime_cli_response")

    def test_runtime_cli_provider_compact_compacts_unexpected_exception_detail(self) -> None:
        state = self._state()
        detail = "Traceback\nAuthorization: Bearer secret-token\n" + ("failure detail\n" * 20_000)

        with self._trusted_runtime():
            with patch("core.api.runtime_cli_api.run_cli_json", side_effect=RuntimeError(detail)):
                status, payload = self._invoke_runtime_cli(
                    state,
                    {"argv": ["core", "cli", "run", "broken"], "output_profile": "provider_compact"},
                )

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["status_code"], 400)
        self.assertEqual(payload["error"], "cli_command_failed")
        self.assertIn("[tool output compacted]", payload["detail"])
        self.assertNotIn("secret-token", payload["detail"])
        self.assertEqual(payload["output_compaction"]["fields"], ["detail"])

    def test_runtime_cli_full_profile_leaves_exception_detail_full(self) -> None:
        state = self._state()
        detail = "full detail " * 2000

        with self._trusted_runtime():
            with patch("core.api.runtime_cli_api.run_cli_json", side_effect=RuntimeError(detail)):
                status, payload = self._invoke_runtime_cli(
                    state,
                    {"argv": ["core", "cli", "run", "broken"], "output_profile": "full"},
                )

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["status_code"], 400)
        self.assertEqual(payload["detail"], detail)
        self.assertNotIn("output_compaction", payload)

    def test_runtime_cli_uses_payload_error_status_for_http_response(self) -> None:
        state = self._state()

        with self._trusted_runtime():
            with patch(
                "core.api.runtime_cli_api.run_cli_json",
                return_value={"status_code": 400, "error": "unsupported"},
            ):
                status, payload = self._invoke_runtime_cli(state, {"argv": ["app", "vault", "cli", "run", "vault"]})

        self.assertEqual(status, "400 Bad Request")
        self.assertEqual(payload["status_code"], 400)
        self.assertEqual(payload["error"], "unsupported")

    def test_runtime_cli_rejects_invalid_runtime_session_record(self) -> None:
        def raise_invalid_session(_session_id: str):
            raise ValueError("Unsupported runtime thread visibility `not-hidden`.")

        state = self._state(get_session=raise_invalid_session)

        with self._trusted_runtime():
            with patch("core.api.runtime_cli_api.run_cli_json") as run_cli:
                status, payload = self._invoke_runtime_cli(state, {"argv": ["core", "cli", "run", "docs"]})

        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(payload["error"], "runtime_session_not_found")
        run_cli.assert_not_called()

    def _state(self, *, get_session=None) -> SimpleNamespace:
        if get_session is None:
            get_session = lambda _session_id: SimpleNamespace(
                effective_mode="sandbox",
                owner_user_id="user:admin",
                session_id="sess-1",
                status="running",
                workspace_id="default",
            )
        return SimpleNamespace(
            runtime_store=SimpleNamespace(
                get_session=get_session
            )
        )

    def _trusted_runtime(self):
        claims_patch = patch(
            "core.api.runtime_cli_api._runtime_claims",
            return_value=({"runtime_session_id": "sess-1", "workspace_id": "default", "mode": "sandbox"}, None),
        )
        authority_patch = patch(
            "core.api.runtime_cli_api._runtime_actor_authority",
            return_value=("admin", "user:admin", "admin"),
        )
        stack = ExitStack()
        stack.enter_context(claims_patch)
        stack.enter_context(authority_patch)
        return stack

    def _invoke_runtime_cli(self, state: SimpleNamespace, payload: dict) -> tuple[str, dict]:
        body = json.dumps(payload).encode("utf-8")
        status_holder: list[str] = []

        response = handle_runtime_cli_api(
            state,
            {
                "CONTENT_LENGTH": str(len(body)),
                "PATH_INFO": "/api/runtime/cli",
                "REQUEST_METHOD": "POST",
                "wsgi.input": BytesIO(body),
            },
            lambda status, _headers: status_holder.append(status),
            start_path=Path("/repo"),
        )

        self.assertIsNotNone(response)
        assert response is not None
        return status_holder[0], json.loads(b"".join(response).decode("utf-8"))

if __name__ == "__main__":
    unittest.main()
