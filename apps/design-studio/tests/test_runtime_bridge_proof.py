from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
PROOF_PATH = ROOT / "apps/design-studio/service/verify_runtime_bridge_spike.py"
FIXTURE_PATH = ROOT / "apps/design-studio/tests/fixtures/rejected_a_acp_shim.py"
ADR_PATH = ROOT / "docs/architecture/design_studio_runtime_bridge.md"
REAL_SPIKE_PATH = ROOT / "apps/design-studio/tests/spike_rejected_a_acp.mjs"


def _proof_module():
    spec = importlib.util.spec_from_file_location("verify_runtime_bridge_spike", PROOF_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesignStudioRuntimeBridgeProofTests(unittest.TestCase):
    def test_g3_rejects_a_acp_and_selects_generic_streaming_bridge(self) -> None:
        proof = _proof_module()
        evidence = proof.load_evidence()

        proof.verify_decision(evidence)
        result = proof.run_selected_b_contract_proof()

        self.assertEqual(evidence["selection"], "B")
        self.assertTrue(all(result.values()))

    def test_rejected_acp_fixture_is_protocol_only_and_has_no_provider_secret(self) -> None:
        completed = subprocess.run(
            [str(FIXTURE_PATH), "--version"],
            check=True,
            capture_output=True,
            env={"PATH": "/usr/bin:/bin"},
            text=True,
        )

        self.assertEqual(completed.stdout.strip(), "maverick-acp-spike 1.0")
        fixture_source = FIXTURE_PATH.read_text(encoding="utf-8")
        self.assertIn("provider_secret_names", fixture_source)
        self.assertIn("no model or tool loop", fixture_source)
        self.assertIn("OPEN_DESIGN_RUN_ID", fixture_source)
        self.assertIn("MAVERICK_ACP_SPIKE_TRACE", fixture_source)
        self.assertNotIn("ANTHROPIC_API_KEY", fixture_source)
        self.assertNotIn("OPENAI_API_KEY", fixture_source)
        self.assertNotIn(sys.executable, completed.stdout)

    def test_adr_freezes_message_schema_ownership_recovery_and_idempotency(self) -> None:
        adr = ADR_PATH.read_text(encoding="utf-8")

        self.assertIn("Decision: option B", adr)
        self.assertIn("### Generic core request", adr)
        self.assertIn("### Generic core event", adr)
        self.assertIn("### App-owned mapping", adr)
        self.assertIn("## Message sequences", adr)
        self.assertIn("### Restart and resume", adr)
        self.assertIn("## Ownership and attribution", adr)
        self.assertIn("## Idempotency", adr)
        self.assertIn("## Failure behavior", adr)
        self.assertIn("--upstream-root /tmp/maverick-opendesign-0-16-1", adr)
        self.assertIn("spike_rejected_a_acp.mjs", adr)
        self.assertTrue(REAL_SPIKE_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
