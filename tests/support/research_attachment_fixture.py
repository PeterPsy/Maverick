"""ResearchAttachmentFixture fixtures extracted without changing assertions."""

from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from core.runtime.provider_input_context import runtime_provider_input_sources
from tests.support.hosted_agentic_harness import HostedAgenticHarness


class ResearchAttachmentFixture:
    def setUp(self):
        self.harness = HostedAgenticHarness(self)
        self.session = replace(self.harness.session, runtime_profile="research")
        self.state = SimpleNamespace(
            workspace_store=SimpleNamespace(get_resource_classification=lambda **_kwargs: None),
            repository_root=Path(__file__).resolve().parents[2],
        )

    def attachment(self, name, raw, media_type):
        relative = f"storage/uploaded/fixture/{name}"
        target = Path(self.session.workspace_root) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {"name": name, "relativePath": relative, "type": media_type, "size": len(raw)}

    def sources(self, attachments, text="Analyze these."):
        return runtime_provider_input_sources(
            self.state, session=self.session, turn_id="turn-hosted", input_text=text,
            attachments=attachments, app_references=[{"app_id": "hidden"}],
        )
