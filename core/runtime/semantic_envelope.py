"""Canonical Core-owned semantic envelope for agentic runtime turns."""

from __future__ import annotations

from pathlib import Path

from core.providers.agentic_protocol import (
    AgenticProviderPrivateState,
    AgenticRequestPhase,
    AgenticToolResult,
    HOSTED_FINALIZATION_INSTRUCTION,
)
from core.runtime.confined_filesystem import (
    ConfinedWorkspaceFilesystem,
    ResourceClassificationResolver,
)
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassifier,
)
from core.runtime.semantic_context_blocks import SemanticContextMaterializer
from core.runtime.semantic_envelope_models import (
    HOSTED_SEMANTIC_PROJECTION_COMPILER_ID,
    HOSTED_SEMANTIC_PROJECTION_COMPILER_REVISION,
    SEMANTIC_ENVELOPE_SCHEMA_VERSION,
    SemanticEnvelope,
    SemanticEnvelopeBlock,
    finalize_semantic_envelope,
    make_semantic_block,
    platform_classification,
    semantic_projection_digest,
)
from core.runtime.semantic_tool_blocks import append_semantic_tool_blocks
from core.runtime.tool_catalog import RuntimeToolCatalog


class HostedSemanticEnvelopeCompiler:
    """Compile canonical blocks independently from provider wire rendering."""

    compiler_id = HOSTED_SEMANTIC_PROJECTION_COMPILER_ID
    compiler_revision = HOSTED_SEMANTIC_PROJECTION_COMPILER_REVISION

    def __init__(
        self,
        *,
        classifier: HostedContentClassifier,
        platform_instruction: str,
        resource_classification_resolver: ResourceClassificationResolver | None = None,
        classification_revalidator=None,
    ) -> None:
        self.classifier = classifier
        self.classification_revalidator = classification_revalidator
        self._materializer = SemanticContextMaterializer(
            classifier=classifier,
            platform_instruction=platform_instruction,
            resource_classification_resolver=resource_classification_resolver,
        )
        self._resource_classification_resolver = resource_classification_resolver

    def compile(
        self,
        *,
        context,
        input_text: str,
        catalog: RuntimeToolCatalog,
        tool_results: tuple[AgenticToolResult, ...],
        provider_private_state: AgenticProviderPrivateState | None,
        request_phase: AgenticRequestPhase,
    ) -> SemanticEnvelope:
        """Build every applicable semantic block or fail before provider dispatch."""
        filesystem = self._filesystem(context)
        blocks: list[SemanticEnvelopeBlock] = []
        try:
            self._materializer.append_platform(blocks, context=context)
            self._materializer.append_workspace(
                blocks,
                context=context,
                filesystem=filesystem,
            )
            self._materializer.append_agent(blocks, context=context)
            self._materializer.append_inputs(
                blocks,
                context=context,
                input_text=input_text,
            )
            self._materializer.append_skills(
                blocks,
                context=context,
                filesystem=filesystem,
            )
            if request_phase != "exploration":
                blocks.append(
                    make_semantic_block(
                        blocks,
                        context=context,
                        kind="content",
                        role="system",
                        provenance="finalization_instruction",
                        content_type="text/plain",
                        content=HOSTED_FINALIZATION_INSTRUCTION,
                        classification=platform_classification(
                            "core:hosted-finalization-instruction",
                            "1",
                            HOSTED_FINALIZATION_INSTRUCTION,
                        ),
                    )
                )
            append_semantic_tool_blocks(
                blocks,
                context=context,
                catalog=catalog,
                tool_results=tool_results,
                provider_private_state=provider_private_state,
                classifier=self.classifier,
                classification_revalidator=self.classification_revalidator,
            )
        except HostedAgenticLoopError:
            raise
        except Exception as error:
            raise HostedAgenticLoopError(
                "semantic_envelope_materialization_failed"
            ) from error
        finally:
            filesystem.close()
        if not blocks or any(not block.required for block in blocks):
            raise HostedAgenticLoopError("semantic_envelope_incomplete")
        return finalize_semantic_envelope(context=context, blocks=blocks)

    def _filesystem(self, context) -> ConfinedWorkspaceFilesystem:
        try:
            return ConfinedWorkspaceFilesystem(
                workspace_id=context.session.workspace_id,
                workspace_root=Path(context.session.workspace_root),
                classification_resolver=self._resource_classification_resolver,
            )
        except Exception as error:
            raise HostedAgenticLoopError(
                "semantic_workspace_boundary_unavailable"
            ) from error


__all__ = [
    "HOSTED_SEMANTIC_PROJECTION_COMPILER_ID",
    "HOSTED_SEMANTIC_PROJECTION_COMPILER_REVISION",
    "HostedSemanticEnvelopeCompiler",
    "SEMANTIC_ENVELOPE_SCHEMA_VERSION",
    "SemanticEnvelope",
    "SemanticEnvelopeBlock",
    "semantic_projection_digest",
]
