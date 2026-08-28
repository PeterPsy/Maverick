"""Materialize tool schema, result, and provider-state semantic blocks."""

from __future__ import annotations

from core.providers.agentic_protocol import (
    AgenticProviderPrivateState,
    AgenticToolResult,
)
from core.runtime.hosted_agentic_models import (
    HostedContentClassification,
    HostedContentClassifier,
)
from core.runtime.semantic_envelope_models import (
    SemanticEnvelopeBlock,
    make_semantic_block,
    platform_classification,
)
from core.runtime.tool_catalog import RuntimeToolCatalog


def append_semantic_tool_blocks(
    blocks: list[SemanticEnvelopeBlock],
    *,
    context,
    catalog: RuntimeToolCatalog,
    tool_results: tuple[AgenticToolResult, ...],
    provider_private_state: AgenticProviderPrivateState | None,
    classifier: HostedContentClassifier,
) -> None:
    for descriptor in catalog.descriptors:
        blocks.append(
            make_semantic_block(
                blocks,
                context=context,
                kind="tool_schema",
                role="system",
                provenance="tool_schema",
                content_type="application/json",
                content={
                    "name": descriptor.provider_name,
                    "description": descriptor.description,
                    "input_schema": descriptor.input_schema,
                },
                classification=platform_classification(
                    f"core-tool-schema:{descriptor.handle}",
                    str(descriptor.certified_tcb_component or ""),
                ),
            )
        )
    for result in tool_results:
        metadata = result.source_metadata
        classification = (
            HostedContentClassification(
                metadata.source_data_class,
                metadata.source_trust_level,
                source_ref=metadata.source_ref,
                source_revision=metadata.source_revision,
                resource_identity=metadata.resource_identity,
                classification_revision=metadata.classification_revision,
            )
            if metadata is not None
            else classifier(context, "tool_result", result.content)
        )
        blocks.append(
            make_semantic_block(
                blocks,
                context=context,
                kind="tool_result",
                role="user",
                provenance="tool_result",
                content_type=result.content_type,
                content=result.content,
                classification=classification,
                source_ref=result.provider_tool_call_id,
            )
        )
    if provider_private_state is None:
        return
    blocks.append(
        make_semantic_block(
            blocks,
            context=context,
            kind="provider_state",
            role="assistant",
            provenance="provider_state",
            content_type=provider_private_state.content_type,
            content=provider_private_state.content,
            classification=HostedContentClassification(
                provider_private_state.effective_data_class,
                provider_private_state.effective_trust_level,
                source_ref=(
                    "provider-state:"
                    + (provider_private_state.provider_request_id or "legacy")
                ),
                source_revision=(provider_private_state.turn_generation or "legacy"),
                resource_identity=(
                    "provider-state:"
                    + context.session.session_id
                    + ":"
                    + (provider_private_state.provider_request_id or "legacy")
                ),
                classification_revision=(
                    1
                    if provider_private_state.provider_request_id
                    and provider_private_state.turn_generation
                    else None
                ),
            ),
        )
    )
