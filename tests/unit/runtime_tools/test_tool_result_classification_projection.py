from __future__ import annotations

from dataclasses import replace
import unittest

from core.cli.command_registry import CliCommandRegistry
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
)
from core.runtime.tool_catalog import (
    RuntimeToolActorContext,
    RuntimeToolSurfaceResult,
)
from core.runtime.tool_errors import RuntimeToolError


HEX_WRAPPED_PAN = "deadbeef4111111111111111cafebabedeadbeef"
DIGEST_WITH_LUHN_SUBSEQUENCE = (
    "20914ef24928d26319dd8ac4ff04b2204cf4630440387733486e3cc0cc2084f0"
)


class ToolResultClassificationProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role="admin",
            workspace_role="owner",
            session_id="session-hosted",
            execution_mode="full-access",
        )
        self.resolve = build_hosted_tool_result_admission_resolver(
            cli_registry=CliCommandRegistry(),
            mcp_registry=McpToolRegistry(),
        )

    def test_typed_core_metadata_projection_never_hides_output_bytes(
        self,
    ) -> None:
        ordinary_payload = {
            "exit_code": 0,
            "output": "ordinary output",
            "mutation_scope_digest": DIGEST_WITH_LUHN_SUBSEQUENCE,
        }
        ordinary = self.resolve(
            "core-capability:shell.run",
            {"argv": ["fixture"]},
            ordinary_payload,
            self.actor,
        )
        sensitive = self.resolve(
            "core-capability:shell.run",
            {"argv": ["fixture"]},
            {**ordinary_payload, "output": HEX_WRAPPED_PAN},
            self.actor,
        )

        self.assertIsInstance(ordinary, RuntimeToolSurfaceResult)
        self.assertIsNotNone(ordinary.classification_projection)
        self.assertEqual(ordinary.classification.data_class, "unclassified")
        self.assertEqual(
            sensitive.classification.data_class,
            "regulated_or_customer_data",
        )
        tampered = {**ordinary.payload, "output": "changed after binding"}
        with self.assertRaisesRegex(
            RuntimeToolError,
            "tool_result_classification_projection_invalid",
        ):
            ordinary.classification_projection.resolve(tampered)

        forged = replace(
            ordinary.classification_projection,
            projected_payload=b"{}",
        )
        with self.assertRaisesRegex(
            RuntimeToolError,
            "tool_result_classification_projection_invalid",
        ):
            forged.resolve(ordinary.payload)


if __name__ == "__main__":
    unittest.main()
