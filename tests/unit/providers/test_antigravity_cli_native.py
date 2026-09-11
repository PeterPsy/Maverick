"""Executable Antigravity stream-json lifecycle and containment proof."""

import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.antigravity_cli_sandbox import antigravity_stream_launch_spec
from core.providers.antigravity_cli_sandbox import (
    ANTIGRAVITY_OUTER_SANDBOX_COMMAND_ENV,
    resolve_antigravity_outer_sandbox,
)
from core.providers.agentic_adapter import RuntimeRecoveryContext
from core.providers.native_agent_builtins import (
    build_antigravity_cli_candidate_definition,
)
from core.providers.native_structured_cli_transport import NativeStructuredCliError
from core.runtime.agentic_execution import execute_agentic_runtime_turn
from core.runtime.resolved_runtime_engine import (
    ResolvedRuntimeEngine,
    build_optional_local_launch_spec,
)
from tests.unit.providers.antigravity_cli_fixture import AntigravityCliFixture


class AntigravityCliNativeTest(AntigravityCliFixture, unittest.IsolatedAsyncioTestCase):
    async def test_successful_turn_and_resume_through_real_core_executor(self):
        authority = self.core_authority()
        for prompt in ("first", "second"):
            events, accepted, sent, threads = [], [], [], []
            result = await execute_agentic_runtime_turn(
                session=self.session,
                provider_state=self.state,
                adapter=self.controller,
                input_text=prompt,
                correlation_id="turn",
                effective_authority=authority,
                local_launch_spec=self.spec,
                event_sink=events.append,
                on_provider_accepted=accepted.append,
                on_provider_turn_start_sent=sent.append,
                on_provider_thread_id=threads.append,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertIsNone(result.failure_reason_code)
            self.assertEqual(result.output_text, "answer:" + prompt)
            self.assertEqual(len(accepted), 1)
            self.assertEqual(len(sent), 1)
            self.assertEqual(threads, ["fixture-conversation"])
            usage = next(event for event in events if event.event_type == "provider.usage")
            self.assertEqual(usage.payload["semantics"], "cumulative")
            self.assertEqual(usage.payload["source"], "antigravity_cli")
            self.state.provider_thread_id = threads[0]
            await self.controller.close(self.context)
        startups = [message["startup"] for message in self.messages() if "startup" in message]
        self.assertEqual(len(startups), 2)
        self.assertIn("--conversation", startups[1]["argv"])
        self.assertIn("fixture-conversation", startups[1]["argv"])

    async def test_launch_is_pinned_machine_readable_and_never_bypasses_permissions(self):
        command = self.spec.command
        sandboxed = self.sandboxed_spec.command
        workspace = str(Path(self.session.workspace_root))
        self.assertIn(
            ["--ro-bind", workspace, workspace],
            [sandboxed[index : index + 3] for index in range(len(sandboxed) - 2)],
        )
        skills_root = str(
            self.root
            / "runtime/antigravity-home/.gemini/antigravity-cli/skills"
        )
        self.assertIn(
            ["--ro-bind", skills_root, skills_root],
            [sandboxed[index : index + 3] for index in range(len(sandboxed) - 2)],
        )
        self.assertEqual(command.count("stream-json"), 2)
        self.assertIn("--sandbox", command)
        self.assertIn("--disable-slash-commands", command)
        self.assertIn("--model", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertIn("/usr/local/lib", self.spec.readable_roots)
        self.assertEqual(self.spec.env_overrides["HOME"], str(self.root / "runtime/antigravity-home"))
        self.assertNotEqual(self.spec.env_overrides["HOME"], str(Path.home()))
        self.assertNotIn("GEMINI_API_KEY", self.spec.env_overrides)
        self.assertNotIn("MAVERICK_PROVIDER_SECRET", self.spec.env_overrides)
        settings_path = (
            Path(self.spec.env_overrides["HOME"])
            / ".gemini/antigravity-cli/settings.json"
        )
        self.assertEqual(
            json.loads(settings_path.read_text(encoding="utf-8")),
            {
                "artifactReviewPolicy": "asks-for-review",
                "enableTerminalSandbox": True,
                "permissions": {
                    "allow": [
                        "command(maverick)",
                        "unsandboxed(maverick)",
                    ],
                },
                "toolPermission": "proceed-in-sandbox",
            },
        )
        self.assertEqual(settings_path.stat().st_mode & 0o777, 0o600)
        token_path = settings_path.parent / "antigravity-oauth-token"
        self.assertEqual(token_path.read_text(encoding="utf-8"), "fixture-oauth-token")
        self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.spec.resolved_secret_refs, [])
        self.assertIsNone(self.spec.credential_binding_id)
        self.assertEqual(self.spec.writable_roots, [str(self.root / "runtime")])
        self.assertTrue(
            (self.root / "runtime/bin/maverick").is_file()
        )
        self.assertIn("MAVERICK_RUNTIME_API_TOKEN", self.spec.env_overrides)
        self.assertTrue(
            self.spec.env_overrides["PATH"].startswith(
                str(self.root / "runtime/bin")
            )
        )

    async def test_optional_outer_sandbox_is_content_and_owner_pinned(self):
        candidate = self.root / "dedicated-bwrap"
        candidate.write_bytes(b"reviewed outer sandbox")
        candidate.chmod(0o755)
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        environment = {ANTIGRAVITY_OUTER_SANDBOX_COMMAND_ENV: str(candidate)}
        with (
            patch.dict(os.environ, environment),
            patch(
                "core.providers.antigravity_cli_sandbox."
                "ANTIGRAVITY_OUTER_SANDBOX_SHA256",
                digest,
            ),
            patch(
                "core.providers.antigravity_cli_sandbox."
                "ANTIGRAVITY_OUTER_SANDBOX_OWNER_UID",
                os.getuid(),
            ),
        ):
            self.assertEqual(resolve_antigravity_outer_sandbox(), candidate)
            spec = antigravity_stream_launch_spec(
                SimpleNamespace(
                    session=self.session,
                    binding=self.binding,
                    secret_env={},
                ),
                command=self.engine.command,
                dependency_roots=self.engine.dependency_roots,
                auth_home=self.auth_home,
            )
            self.assertEqual(spec.command[0], str(candidate))
            candidate.chmod(0o775)
            with self.assertRaisesRegex(
                NativeStructuredCliError,
                "outer_sandbox_invalid",
            ):
                resolve_antigravity_outer_sandbox()

    async def test_health_degrades_for_an_invalid_outer_sandbox(self):
        with patch(
            "core.providers.antigravity_cli_native."
            "resolve_antigravity_outer_sandbox",
            side_effect=NativeStructuredCliError(
                "antigravity_outer_sandbox_invalid"
            ),
        ):
            health = await self.engine.health(SimpleNamespace())

        self.assertEqual(health.status, "degraded")
        self.assertEqual(
            health.reason_codes,
            ("antigravity_outer_sandbox_invalid",),
        )

    async def test_launch_requires_private_operator_oauth_profile(self):
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "antigravity_oauth_credential_missing",
        ):
            antigravity_stream_launch_spec(
                SimpleNamespace(
                    session=self.session,
                    binding=self.binding,
                    secret_env={},
                ),
                command=str(self.root / "agy-fixture"),
                dependency_roots=(),
                auth_home=self.root / "missing-auth-home",
            )

    async def test_launch_rejects_api_key_or_provider_binding(self):
        for secret_env, credential_binding_id in (
            ({"MAVERICK_PROVIDER_SECRET": "wrong-credential-kind"}, None),
            ({}, "google-api-binding"),
        ):
            with self.subTest(
                secret=bool(secret_env),
                binding=credential_binding_id,
            ):
                binding = SimpleNamespace(
                    **{
                        **vars(self.binding),
                        "credential_binding_id": credential_binding_id,
                    }
                )
                with self.assertRaisesRegex(
                    NativeStructuredCliError,
                    "antigravity_oauth_boundary_invalid",
                ):
                    antigravity_stream_launch_spec(
                        SimpleNamespace(
                            session=self.session,
                            binding=binding,
                            secret_env=secret_env,
                        ),
                        command=str(self.root / "agy-fixture"),
                        dependency_roots=(),
                        auth_home=self.auth_home,
                    )

    async def test_resolved_runtime_requests_the_agentic_launch_builder(self):
        resolved = ResolvedRuntimeEngine(
            build_antigravity_cli_candidate_definition(),
            None,
            self.controller,
            None,
        )
        captured = {}

        def builder(_state, **kwargs):
            captured.update(kwargs)
            return "launch"

        result = build_optional_local_launch_spec(
            resolved,
            builder,
            object(),
            session=self.session,
        )

        self.assertEqual(result, "launch")
        self.assertIs(captured["agentic_adapter"], self.controller)
        self.assertIsNone(captured["runtime_adapter"])

    async def test_invalid_streams_never_complete_successfully_through_core(self):
        authority = self.core_authority()
        for prompt in ("empty", "malformed", "oversized", "mismatch-output"):
            with self.subTest(prompt=prompt):
                prepared = await self.controller.connect(self.context)
                events = []
                with self.assertRaises(NativeStructuredCliError):
                    await execute_agentic_runtime_turn(
                        session=self.session,
                        provider_state=self.state,
                        adapter=self.controller,
                        input_text=prompt,
                        correlation_id="turn",
                        effective_authority=authority,
                        local_launch_spec=self.spec,
                        event_sink=events.append,
                    )
                self.assertIsNotNone(prepared.prepared_handle.process.returncode)
                self.assertFalse(
                    any(event.event_type == "runtime.output.final" for event in events)
                )

    async def test_connect_stream_final_resume_and_close(self):
        prepared = await self.controller.connect(self.context)
        self.state.provider_thread_id = prepared.provider_state_updates[
            "provider_thread_id"
        ]
        client = prepared.prepared_handle
        self.assertEqual(prepared.metadata["steering_mode"], "safe_next_turn")
        self.assertEqual(self.final_text(await self.collect("first")), "answer:first")
        recovered = await self.controller.resume(
            RuntimeRecoveryContext(
                session=self.session,
                binding=self.binding,
                provider_state=self.state,
                local_launch_spec=self.spec,
            )
        )
        self.assertTrue(recovered.recovered)
        self.assertEqual(
            recovered.provider_state_updates["provider_thread_id"],
            self.state.provider_thread_id,
        )
        self.assertIsNotNone(client.process.returncode)
        self.assertEqual(self.final_text(await self.collect("second")), "answer:second")
        self.assertTrue((await self.controller.cleanup(self.context)).closed)

    async def test_tool_and_permission_steps_are_structured(self):
        tool_events = await self.collect("tool")
        self.assertEqual(self.final_text(tool_events), "tool:fixture")
        projected_tools = [
            event
            for event in tool_events
            if event.event_type.startswith("runtime.tool_call.")
        ]
        self.assertEqual(
            [event.event_type for event in projected_tools],
            ["runtime.tool_call.started", "runtime.tool_call.completed"],
        )
        self.assertEqual(projected_tools[0].payload["argument_names"], ["CommandLine"])
        self.assertIn("arguments_sha256", projected_tools[0].payload)
        self.assertNotIn("arguments", projected_tools[0].payload)
        self.assertIn("output_sha256", projected_tools[1].payload)
        self.assertNotIn("output", projected_tools[1].payload)
        permission_events = await self.collect("permission")
        self.assertEqual(self.final_text(permission_events), "Permission denied")
        failure = next(
            event
            for event in permission_events
            if event.event_type == "runtime.tool_call.failed"
        )
        self.assertEqual(failure.payload["error_type"], "permission_denied")
        self.assertNotIn("error_message", failure.payload)

        observed_error = await self.collect("tool-error-state")
        self.assertEqual(self.final_text(observed_error), "Tool failed safely")
        projected_error = [
            event
            for event in observed_error
            if event.event_type.startswith("runtime.tool_call.")
        ]
        self.assertEqual(
            [event.event_type for event in projected_error],
            ["runtime.tool_call.started", "runtime.tool_call.failed"],
        )
        self.assertEqual(projected_error[-1].payload["error_type"], "TOOL_ERROR")
        self.assertNotIn("error_message", projected_error[-1].payload)

    async def test_bad_sequence_identity_and_permission_mode_fail_closed(self):
        for prompt, reason in (
            ("duplicate-init", "event_sequence_invalid"),
            ("wrong-conversation", "conversation_mismatch"),
            ("error", "result_error"),
        ):
            with self.subTest(prompt=prompt):
                prepared = await self.controller.connect(self.context)
                with self.assertRaisesRegex(NativeStructuredCliError, reason):
                    await self.collect(prompt)
                self.assertIsNotNone(prepared.prepared_handle.process.returncode)

        untrusted = replace(
            self.spec,
            env_overrides={
                **self.spec.env_overrides,
                "ANTIGRAVITY_FIXTURE_PERMISSION": "always-proceed",
            },
        )
        self.context.local_launch_spec = untrusted
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "permission_mode_untrusted",
        ):
            await self.controller.connect(self.context)

        self.context.local_launch_spec = replace(
            self.spec,
            env_overrides={
                **self.spec.env_overrides,
                "ANTIGRAVITY_FIXTURE_MISSING_TOOL": "1",
            },
        )
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "toolset_incomplete",
        ):
            await self.controller.connect(self.context)

    async def test_resume_identity_mismatch_fails_closed(self):
        self.state.provider_thread_id = "fixture-conversation"
        self.context.local_launch_spec = replace(
            self.spec,
            env_overrides={
                **self.spec.env_overrides,
                "ANTIGRAVITY_FIXTURE_MISMATCH_RESUME": "1",
            },
        )
        with self.assertRaisesRegex(
            NativeStructuredCliError,
            "resume_identity_mismatch",
        ):
            await self.controller.connect(self.context)

    async def test_timeout_reaps_protocol_process_tree(self):
        prepared = await self.controller.connect(self.context)
        with self.assertRaises(TimeoutError):
            await self.collect("fork", timeout=0.2)
        self.assertIsNotNone(prepared.prepared_handle.process.returncode)
        child = int(self.trace.with_suffix(".pid").read_text())
        stat = Path(f"/proc/{child}/stat")
        for _ in range(40):
            if not stat.exists() or stat.read_text().split()[2] == "Z":
                break
            await asyncio.sleep(0.05)
        else:
            self.fail("Antigravity fixture child process survived cleanup")


if __name__ == "__main__":
    unittest.main()
