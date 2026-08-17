"""Build one normalized hosted request through mandatory per-block egress."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from core.egress.agentic_models import (
    AgenticEgressContentBlock,
    AgenticEgressPolicy,
)
from core.egress.agentic_policy import AgenticEgressEvaluator
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticProviderPrivateState,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
    AgenticToolResult,
)
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassifier,
)
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
    require_agentic_feature,
)
from core.runtime.tool_catalog import RuntimeToolCatalog


class HostedAgenticRequestBuilder:
    """Serialize only content approved for the pinned provider and upstream."""

    def __init__(
        self,
        *,
        egress_evaluator: AgenticEgressEvaluator,
        classifier: HostedContentClassifier,
    ) -> None:
        self.egress_evaluator = egress_evaluator
        self.classifier = classifier

    def build(
        self,
        *,
        context,
        step: int,
        input_text: str,
        catalog: RuntimeToolCatalog,
        tool_results: tuple[AgenticToolResult, ...],
        provider_private_state: AgenticProviderPrivateState | None,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
        max_output_tokens: int,
    ) -> AgenticModelRequest:
        binding = context.binding
        request_id = str(
            uuid5(
                NAMESPACE_URL,
                f"maverick:hosted-request:{context.session.session_id}:{context.correlation_id}:{step}",
            )
        )
        content_blocks: list[AgenticRequestContentBlock] = []
        if context.session.system_prompt:
            content_blocks.append(
                self._content_block(
                    context=context,
                    request_id=request_id,
                    index=len(content_blocks),
                    role="system",
                    provenance="platform_instruction",
                    content=context.session.system_prompt,
                    content_type="text/plain",
                    egress_policy=egress_policy,
                    destination_upstream_id=destination_upstream_id,
                )
            )
        content_blocks.append(
            self._content_block(
                context=context,
                request_id=request_id,
                index=len(content_blocks),
                role="user",
                provenance="user_input",
                content=input_text,
                content_type="text/plain",
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
            )
        )
        tools = tuple(
            self._tool_definition(
                context=context,
                request_id=request_id,
                index=index,
                descriptor=descriptor,
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
            )
            for index, descriptor in enumerate(catalog.descriptors)
        )
        private_state = self._private_state(
            context=context,
            request_id=request_id,
            state=provider_private_state,
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
        )
        approved_tool_results = tuple(
            self._request_tool_result(
                context=context,
                request_id=request_id,
                result=result,
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
            )
            for result in tool_results
        )
        return AgenticModelRequest(
            schema_version="1",
            request_id=request_id,
            correlation_id=context.correlation_id,
            model_id=binding.model_id,
            reasoning_effort=binding.reasoning_effort,
            content_blocks=tuple(content_blocks),
            tool_definitions=tools,
            tool_results=approved_tool_results,
            provider_private_state=private_state,
            routing_constraint=binding.routing_constraint_snapshot,
            max_output_tokens=max_output_tokens,
        )

    def _content_block(
        self,
        *,
        context,
        request_id: str,
        index: int,
        role: str,
        provenance: str,
        content: object,
        content_type: str,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
    ) -> AgenticRequestContentBlock:
        classification = self.classifier(context, provenance, content)
        content_block_id = f"{request_id}:content:{index}"
        exported = self._evaluate(
            context=context,
            content_block_id=content_block_id,
            provenance=provenance,
            content=content,
            content_type=content_type,
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
            classification=classification,
        )
        return AgenticRequestContentBlock(
            content_block_id=content_block_id,
            role=role,
            data_class=classification.data_class,
            provenance=provenance,
            trust_level=classification.trust_level,
            content_type=content_type,
            content=exported,
        )

    def _request_tool_result(
        self,
        *,
        context,
        request_id: str,
        result: AgenticToolResult,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
    ) -> AgenticToolResult:
        classification = self.classifier(context, "tool_result", result.content)
        exported = self._evaluate(
            context=context,
            content_block_id=(
                f"{request_id}:tool-result:{result.provider_tool_call_id}"
            ),
            provenance="tool_result",
            content=result.content,
            content_type=result.content_type,
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
            classification=classification,
        )
        return AgenticToolResult(
            provider_tool_call_id=result.provider_tool_call_id,
            provider_tool_name=result.provider_tool_name,
            content_type=result.content_type,
            content=exported,
            is_error=result.is_error,
        )

    def _tool_definition(
        self,
        *,
        context,
        request_id: str,
        index: int,
        descriptor,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
    ) -> AgenticToolDefinition:
        payload = {
            "name": descriptor.provider_name,
            "description": descriptor.description,
            "input_schema": descriptor.input_schema,
        }
        exported = self._evaluate(
            context=context,
            content_block_id=f"{request_id}:tool-schema:{index}",
            provenance="tool_schema",
            content=payload,
            content_type="application/json",
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
        )
        try:
            transformed = json.loads(exported.decode("utf-8"))
            return AgenticToolDefinition(
                name=str(transformed["name"]),
                description=str(transformed["description"]),
                input_schema=dict(transformed["input_schema"]),
            )
        except (UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
            raise HostedAgenticLoopError("tool_schema_egress_invalid") from error

    def _private_state(
        self,
        *,
        context,
        request_id: str,
        state: AgenticProviderPrivateState | None,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
    ) -> AgenticProviderPrivateState | None:
        if state is None:
            return None
        exported = self._evaluate(
            context=context,
            content_block_id=f"{request_id}:provider-state",
            provenance="provider_state",
            content=state.content,
            content_type=state.content_type,
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
        )
        return AgenticProviderPrivateState(
            codec_id=state.codec_id,
            codec_version=state.codec_version,
            schema_version=state.schema_version,
            content_type=state.content_type,
            content=exported,
        )

    def _evaluate(
        self,
        *,
        context,
        content_block_id: str,
        provenance: str,
        content: object,
        content_type: str,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
        classification=None,
    ) -> bytes:
        require_agentic_feature(
            MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
            "agentic_egress_enforcement_disabled",
        )
        classification = classification or self.classifier(context, provenance, content)
        result = self.egress_evaluator.evaluate(
            block=AgenticEgressContentBlock(
                content_block_id=content_block_id,
                session_id=context.session.session_id,
                turn_id=context.correlation_id,
                workspace_id=context.session.workspace_id,
                data_class=classification.data_class,
                provenance=provenance,
                trust_level=classification.trust_level,
                content_type=content_type,
            ),
            content=content,
            destination_provider_id=context.binding.model_provider_id,
            destination_upstream_id=destination_upstream_id,
            policy=egress_policy,
            workspace_root=Path(context.session.workspace_root),
        )
        if not result.decision.export_allowed or result.exported_content is None:
            raise HostedAgenticLoopError("egress_denied")
        return result.exported_content
