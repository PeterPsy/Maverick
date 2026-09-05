"""The second native uses a real ACP child process, not the Codex bridge."""

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from core.providers.gemini_cli_native import GeminiCliNativeAdapter
from core.providers.native_agent_builtins import build_gemini_cli_candidate_installation, build_gemini_cli_candidate_definition
from core.providers.provider_registry import ProviderRegistry
from core.providers.capability_models import RuntimeCapabilitySet
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.execution_binding import canonical_digest


class GeminiCliFixture:
    async def setup_fixture(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        workspace = self.root / "workspace"
        workspace.mkdir()
        self.trace = self.root / "trace.jsonl"
        command = self.root / "gemini-fixture"
        fixture = Path(__file__).resolve().parents[2] / "fixtures/native_acp_peer.py"
        command.write_text(f"#!{sys.executable}\n" + fixture.read_text())
        command.chmod(0o755)
        self.engine = GeminiCliNativeAdapter(command=str(command))
        registry = ProviderRegistry()
        registry.register_native_agent_installation(
            build_gemini_cli_candidate_installation(), definition=build_gemini_cli_candidate_definition(),
            engine_adapter=self.engine,
        )
        self.controller = registry.get_native_agent_controller("gemini-cli")
        self.assertIsNone(self.controller.legacy_adapter)
        self.session = SimpleNamespace(
            session_id="test", workspace_root=str(workspace), workdir=str(workspace),
            runtime_root=str(self.root / "runtime"), effective_mode="sandbox",
        )
        self.binding = SimpleNamespace(model_id="gemini-fixture", credential_binding_id=None, model_revision_policy="provider_alias")
        self.state = SimpleNamespace(provider_thread_id=None)
        # The fixture process replaces only the OS sandbox wrapper. Production
        # launch still uses the real, fail-closed workspace sandbox builder.
        with patch("core.providers.gemini_cli_sandbox.build_bwrap_command", side_effect=lambda **kwargs: kwargs["command"]) as sandbox:
            spec = await self.controller.launch(SimpleNamespace(session=self.session, binding=self.binding, secret_env={}))
            self.assertEqual(sandbox.call_args.kwargs["workspace_root"], workspace)
        self.spec = replace(spec, env_overrides={**spec.env_overrides, "ACP_FIXTURE_TRACE": str(self.trace)})
        self.context = SimpleNamespace(session=self.session, binding=self.binding, provider_state=self.state,
                                       local_launch_spec=self.spec)
        self.launch_patch = patch.object(self.engine, "build_launch_spec", return_value=self.spec)
        self.launch_patch.start()
        self.addCleanup(self.launch_patch.stop)

    def messages(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def core_authority(self):
        # Explicit local fixture authority is not an installed Gemini certificate.
        self.binding.execution_binding_id = "fixture-binding"
        self.session.execution_binding = self.binding
        authority = EffectiveRuntimeAuthority(
            execution_binding_id="fixture-binding", turn_id="turn", certificate_id="fixture-only",
            allowed_capabilities=RuntimeCapabilitySet(
                streaming=True, tool_orchestration=False, cli=False, mcp=False, skill_catalog=False,
                filesystem_list=False, filesystem_read=False, filesystem_write=False, shell=False,
                interrupt=True, same_turn_steering=True, recovery=True, confirmation_resume=False,
                provider_private_state=False, attachment_modalities=(),
            ), allowed_tool_handles=(), execution_mode="sandbox",
            egress_policy_id="fixture-only", policy_revision_set=(), health_revision="fixture",
            authority_digest="", computed_at=datetime.now(tz=UTC),
        )
        return replace(authority, authority_digest=canonical_digest(authority))
