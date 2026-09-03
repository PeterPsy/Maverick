from __future__ import annotations

import base64
import os
from types import SimpleNamespace
import unittest

from core.runtime.attachment_projection import runtime_attachment_read_fences
from core.runtime.provider_input_context import runtime_provider_input_sources
from core.runtime.tool_catalog import RuntimeToolActorContext
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_errors import RuntimeToolError
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class AttachmentReadFencingTest(unittest.TestCase):
    def test_replacement_is_blocked_without_model_supplied_fence(self) -> None:
        harness = HostedAgenticHarness(self)
        context = RuntimeToolActorContext(
            workspace_id="default",
            actor_id="user-1",
            agent_id="chat",
            platform_role=None,
            workspace_role="member",
            session_id="session-hosted",
            execution_mode="full-access",
        )
        cases = (
            ("notes.txt", "text/plain", b"original text", "utf-8"),
            ("scan.bin", "application/octet-stream", b"\x00original", "base64"),
        )
        for name, media_type, original, encoding in cases:
            with self.subTest(encoding=encoding):
                relative_path = f"storage/uploaded/attachment/{name}"
                target = harness.root / "workspaces" / "default" / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original)
                sources = runtime_provider_input_sources(
                    SimpleNamespace(
                        inter_agent_store=None,
                        workspace_store=SimpleNamespace(
                            get_resource_classification=lambda **_kwargs: None
                        ),
                        runtime_input_classification_resolver=None,
                    ),
                    session=harness.session,
                    turn_id="turn-hosted",
                    input_text="",
                    app_references=None,
                    attachments=[
                        {
                            "id": f"attachment-{name}",
                            "name": name,
                            "relativePath": relative_path,
                            "type": media_type,
                            "size": len(original),
                        }
                    ],
                )
                fences = runtime_attachment_read_fences(sources)
                self.assertEqual(len(fences), 1)
                projection = sources[0].content["projection"]
                self.assertEqual(projection, fences[0].projection())
                capabilities = {
                    surface.definition.handle: surface
                    for surface in build_core_runtime_tool_capabilities(
                        workspace_id="default",
                        workspace_root=target.parents[3],
                        attachment_read_fences=fences,
                    )
                }
                read = capabilities["core-capability:filesystem.read"].handler(
                    {"path": relative_path, "encoding": encoding},
                    context,
                    None,
                )
                if encoding == "utf-8":
                    self.assertEqual(read.payload["content"], original.decode())
                else:
                    self.assertEqual(
                        read.payload["content_base64"],
                        base64.b64encode(original).decode("ascii"),
                    )

                replacement = target.with_name(f"replacement-{name}")
                replacement.write_bytes(b"replacement bytes")
                os.replace(replacement, target)

                with self.assertRaisesRegex(
                    RuntimeToolError,
                    "filesystem_resource_changed",
                ):
                    capabilities["core-capability:filesystem.read"].handler(
                        {"path": relative_path, "encoding": encoding},
                        context,
                        None,
                    )
                aliased_path = relative_path.replace(
                    "storage/uploaded/",
                    "storage/./uploaded/",
                    1,
                )
                with self.assertRaisesRegex(
                    RuntimeToolError,
                    "filesystem_resource_changed",
                ):
                    capabilities["core-capability:filesystem.read"].handler(
                        {"path": aliased_path, "encoding": encoding},
                        context,
                        None,
                    )


if __name__ == "__main__":
    unittest.main()
