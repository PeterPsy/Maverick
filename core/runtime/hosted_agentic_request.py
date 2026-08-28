"""Build one normalized hosted request through mandatory per-block egress."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from core.egress.agentic_models import (
    AgenticEgressContentBlock,
    AgenticEgressDecision,
    AgenticEgressPolicy,
)
from core.egress.agentic_policy import AgenticEgressEvaluator
from core.egress.classification import (
    fail_closed_classification,
    validated_classification,
)
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticProviderPrivateState,
    AgenticRequestPhase,
    AgenticRequestContentBlock,
    AgenticSourceMetadata,
    AgenticToolDefinition,
    AgenticToolResult,
    HOSTED_FINALIZATION_INSTRUCTION,
)
from core.providers.certified_execution_tcb import is_certified_tcb_component
from core.providers.errors import CapabilityCertificateError
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassification,
    HostedContentClassifier,
)
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
    require_agentic_feature,
)
from core.runtime.authority import validate_effective_context_capabilities
from core.runtime.tool_catalog import RuntimeToolCatalog

if TYPE_CHECKING:
    from core.runtime.provider_step_models import ProviderStepJournalRecord
    from core.workspaces.data_governance import WorkspaceDataAttestation


HOSTED_TOOL_USE_INSTRUCTION = (
    "Use only function names declared in the current request. Never invent, rename, or infer "
    "a function name. If the declared functions cannot perform a requested operation, explain "
    "that limitation instead of attempting a function call."
)


@dataclass(frozen=True)
class HostedAgenticPreparedRequest:
    """One fully evaluated request whose egress decisions are not committed yet."""

    request: AgenticModelRequest
    workspace_id: str
    egress_decisions: tuple[AgenticEgressDecision, ...]


def hosted_request_lineage_digest(request: AgenticModelRequest) -> str:
    """Hash immutable turn input while excluding Core-owned phase controls."""
    payload = [
        {
            "role": block.role,
            "data_class": block.data_class,
            "provenance": block.provenance,
            "trust_level": block.trust_level,
            "content_type": block.content_type,
            "content_sha256": hashlib.sha256(block.content).hexdigest(),
        }
        for block in request.content_blocks
        if block.provenance != "finalization_instruction"
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def hosted_request_control_digest(request: AgenticModelRequest) -> str:
    """Hash phase controls separately from immutable same-turn source lineage."""
    payload = {
        "request_phase": request.request_phase,
        "max_output_tokens": request.max_output_tokens,
        "tools": tuple(
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in request.tool_definitions
        ),
        "finalization_blocks": tuple(
            {
                "role": block.role,
                "data_class": block.data_class,
                "provenance": block.provenance,
                "trust_level": block.trust_level,
                "content_type": block.content_type,
                "content_sha256": hashlib.sha256(block.content).hexdigest(),
            }
            for block in request.content_blocks
            if block.provenance == "finalization_instruction"
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class HostedAgenticRequestBuilder:
    """Serialize only content approved for the pinned provider and upstream."""

    def __init__(
        self,
        *,
        egress_evaluator: AgenticEgressEvaluator,
        classifier: HostedContentClassifier,
        attestation_resolver: Callable[
            [str], WorkspaceDataAttestation | None
        ]
        | None = None,
    ) -> None:
        self.egress_evaluator = egress_evaluator
        self.classifier = classifier
        self.attestation_resolver = attestation_resolver

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
        request_phase: AgenticRequestPhase = "exploration",
        pairing_source: ProviderStepJournalRecord | None = None,
    ) -> AgenticModelRequest:
        """Build a request and immediately commit all approved egress decisions."""
        return self.commit(
            self.prepare(
                context=context,
                step=step,
                input_text=input_text,
                catalog=catalog,
                tool_results=tool_results,
                provider_private_state=provider_private_state,
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
                max_output_tokens=max_output_tokens,
                request_phase=request_phase,
                pairing_source=pairing_source,
            )
        )

    def prepare(
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
        request_phase: AgenticRequestPhase = "exploration",
        pairing_source: ProviderStepJournalRecord | None = None,
    ) -> HostedAgenticPreparedRequest:
        """Evaluate and transform a candidate without observable egress commit."""
        binding = context.binding
        if request_phase not in {
            "exploration",
            "finalization",
            "finalization_recovery",
        }:
            raise HostedAgenticLoopError("agent_finalization_phase_invalid")
        if request_phase != "exploration" and catalog.descriptors:
            raise HostedAgenticLoopError("agent_finalization_catalog_not_empty")
        self._validate_context_capabilities(context)
        self._validate_catalog_before_egress(catalog)
        request_id = str(
            uuid5(
                NAMESPACE_URL,
                f"maverick:hosted-request:{context.session.session_id}:{context.correlation_id}:{step}",
            )
        )
        egress_decisions: list[AgenticEgressDecision] = []
        content_blocks: list[AgenticRequestContentBlock] = []
        content_blocks.append(
            self._content_block(
                context=context,
                request_id=request_id,
                index=len(content_blocks),
                role="system",
                provenance="platform_instruction",
                content=HOSTED_TOOL_USE_INSTRUCTION,
                content_type="text/plain",
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
                egress_decisions=egress_decisions,
                classification=HostedContentClassification(
                    "public",
                    "trusted_platform",
                    source_ref="core:hosted-tool-use-instruction",
                    source_revision="1",
                    resource_identity="core:hosted-tool-use-instruction:1",
                    classification_revision=1,
                ),
            )
        )
        if context.session.system_prompt:
            content_blocks.append(
                self._content_block(
                    context=context,
                    request_id=request_id,
                    index=len(content_blocks),
                    role="system",
                    provenance="prompt",
                    content=context.session.system_prompt,
                    content_type="text/plain",
                    egress_policy=egress_policy,
                    destination_upstream_id=destination_upstream_id,
                    egress_decisions=egress_decisions,
                )
            )
        input_sources = tuple(getattr(context, "input_sources", ()) or ())
        if input_sources:
            for source in input_sources:
                source_classification = getattr(source, "classification", None)
                content_blocks.append(
                    self._content_block(
                        context=context,
                        request_id=request_id,
                        index=len(content_blocks),
                        role=str(getattr(source, "role", "user") or "user"),
                        provenance=str(
                            getattr(source, "provenance", "unclassified")
                            or "unclassified"
                        ),
                        content=getattr(source, "content", None),
                        content_type=str(
                            getattr(source, "content_type", "application/json")
                            or "application/json"
                        ),
                        egress_policy=egress_policy,
                        destination_upstream_id=destination_upstream_id,
                        egress_decisions=egress_decisions,
                        classification=(
                            HostedContentClassification(
                                source_classification.data_class,
                                source_classification.trust_level,
                                source_ref=source_classification.source_ref,
                                source_revision=source_classification.source_revision,
                                resource_identity=source_classification.resource_identity,
                                classification_revision=(
                                    source_classification.classification_revision
                                ),
                            )
                            if source_classification is not None
                            else None
                        ),
                    )
                )
        else:
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
                    egress_decisions=egress_decisions,
                )
            )
        for skill in tuple(getattr(context, "invoked_skills", ()) or ()):
            content_blocks.append(
                self._content_block(
                    context=context,
                    request_id=request_id,
                    index=len(content_blocks),
                    role="system",
                    provenance="skill",
                    content={
                        "skill_id": str(getattr(skill, "skill_id", "")),
                        "name": str(getattr(skill, "name", "")),
                        "description": str(getattr(skill, "description", "")),
                        "owner_kind": str(getattr(skill, "owner_kind", "")),
                        "owner_id": str(getattr(skill, "owner_id", "")),
                    },
                    content_type="application/json",
                    egress_policy=egress_policy,
                    destination_upstream_id=destination_upstream_id,
                    egress_decisions=egress_decisions,
                )
            )
        if request_phase != "exploration":
            content_blocks.append(
                self._content_block(
                    context=context,
                    request_id=request_id,
                    index=len(content_blocks),
                    role="system",
                    provenance="finalization_instruction",
                    content=HOSTED_FINALIZATION_INSTRUCTION,
                    content_type="text/plain",
                    egress_policy=egress_policy,
                    destination_upstream_id=destination_upstream_id,
                    egress_decisions=egress_decisions,
                    classification=HostedContentClassification(
                        "public",
                        "trusted_platform",
                        source_ref="core:hosted-finalization-instruction",
                        source_revision="1",
                        resource_identity="core:hosted-finalization-instruction:1",
                        classification_revision=1,
                    ),
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
                egress_decisions=egress_decisions,
            )
            for index, descriptor in enumerate(catalog.descriptors)
        )
        private_state = self._private_state(
            context=context,
            request_id=request_id,
            state=provider_private_state,
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
            egress_decisions=egress_decisions,
        )
        approved_tool_results = tuple(
            self._request_tool_result(
                context=context,
                request_id=request_id,
                result=result,
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
                egress_decisions=egress_decisions,
            )
            for result in tool_results
        )
        source_metadata = tuple(
            metadata
            for metadata in (
                *(block.source_metadata for block in content_blocks),
                *(tool.source_metadata for tool in tools),
                *(result.source_metadata for result in approved_tool_results),
                *(() if private_state is None else private_state.source_metadata),
            )
            if metadata is not None
        )
        request = AgenticModelRequest(
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
            source_metadata=source_metadata,
            pairing_source_journal_id=(
                None if pairing_source is None else pairing_source.journal_id
            ),
            pairing_source_turn_id=(
                None if pairing_source is None else pairing_source.turn_id
            ),
            pairing_source_request_id=(
                None if pairing_source is None else pairing_source.request_id
            ),
            request_phase=request_phase,
        )
        return HostedAgenticPreparedRequest(
            request=request,
            workspace_id=context.session.workspace_id,
            egress_decisions=tuple(egress_decisions),
        )

    def commit(self, prepared: HostedAgenticPreparedRequest) -> AgenticModelRequest:
        """Commit every decision only after request-specific budget eligibility."""
        self._commit_egress_decisions(
            workspace_id=prepared.workspace_id,
            decisions=prepared.egress_decisions,
        )
        return prepared.request

    def _commit_egress_decisions(
        self,
        *,
        workspace_id: str,
        decisions: Iterable[AgenticEgressDecision],
    ) -> None:
        for decision in decisions:
            self.egress_evaluator.commit_decision(
                workspace_id=workspace_id,
                decision=decision,
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
        egress_decisions: list[AgenticEgressDecision],
        classification: HostedContentClassification | None = None,
    ) -> AgenticRequestContentBlock:
        classification = classification or self.classifier(context, provenance, content)
        content_block_id = f"{request_id}:content:{index}"
        exported, metadata = self._evaluate(
            context=context,
            content_block_id=content_block_id,
            provenance=provenance,
            content=content,
            content_type=content_type,
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
            egress_decisions=egress_decisions,
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
            source_metadata=metadata,
        )

    def _request_tool_result(
        self,
        *,
        context,
        request_id: str,
        result: AgenticToolResult,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
        egress_decisions: list[AgenticEgressDecision],
    ) -> AgenticToolResult:
        classification = _tool_result_classification(result)
        exported, metadata = self._evaluate(
            context=context,
            content_block_id=(
                f"{request_id}:tool-result:{result.provider_tool_call_id}"
            ),
            provenance="tool_result",
            content=result.content,
            content_type=result.content_type,
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
            egress_decisions=egress_decisions,
            classification=classification,
        )
        return AgenticToolResult(
            provider_tool_call_id=result.provider_tool_call_id,
            provider_tool_name=result.provider_tool_name,
            content_type=result.content_type,
            content=exported,
            is_error=result.is_error,
            source_metadata=metadata,
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
        egress_decisions: list[AgenticEgressDecision],
    ) -> AgenticToolDefinition:
        payload = {
            "name": descriptor.provider_name,
            "description": descriptor.description,
            "input_schema": descriptor.input_schema,
        }
        self._validate_descriptor_schema(descriptor)
        classification = HostedContentClassification(
            "public",
            "trusted_platform",
            source_ref=f"core-tool-schema:{descriptor.handle}",
            source_revision=descriptor.certified_tcb_component,
            resource_identity=f"core-tool-schema:{descriptor.handle}:{descriptor.certified_tcb_component}",
            classification_revision=1,
        )
        exported, metadata = self._evaluate(
            context=context,
            content_block_id=f"{request_id}:tool-schema:{index}",
            provenance="tool_schema",
            content=payload,
            content_type="application/json",
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
            egress_decisions=egress_decisions,
            classification=classification,
        )
        try:
            transformed = json.loads(exported.decode("utf-8"))
            return AgenticToolDefinition(
                name=str(transformed["name"]),
                description=str(transformed["description"]),
                input_schema=dict(transformed["input_schema"]),
                source_metadata=metadata,
            )
        except (UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
            raise HostedAgenticLoopError("tool_schema_egress_invalid") from error

    @staticmethod
    def _validate_context_capabilities(context) -> None:
        authority = getattr(context, "effective_authority", None)
        if authority is None:
            raise HostedAgenticLoopError("runtime_authority_unavailable")
        attachments: list[dict[str, object]] = []
        app_references: list[dict[str, object]] = []
        for source in tuple(getattr(context, "input_sources", ()) or ()):
            provenance = str(getattr(source, "provenance", "") or "")
            if provenance == "attachment":
                attachments.append(
                    {
                        "content_type": str(
                            getattr(source, "capability_modality", "") or ""
                        )
                    }
                )
            elif provenance == "app_reference":
                app_references.append({"server_materialized": True})
        try:
            validate_effective_context_capabilities(
                authority,
                invoked_skills=tuple(getattr(context, "invoked_skills", ()) or ()),
                attachments=attachments,
                app_references=app_references,
            )
        except CapabilityCertificateError as error:
            raise HostedAgenticLoopError(error.reason_code) from error

    @staticmethod
    def _validate_catalog_before_egress(catalog: RuntimeToolCatalog) -> None:
        if catalog.rejections:
            rejection = min(
                catalog.rejections,
                key=lambda item: (item.handle, item.reason_code),
            )
            raise HostedAgenticLoopError(rejection.reason_code)
        for descriptor in catalog.descriptors:
            HostedAgenticRequestBuilder._validate_descriptor_schema(descriptor)

    @staticmethod
    def _validate_descriptor_schema(descriptor) -> None:
        if (
            descriptor.schema_owner_kind != "core"
            or descriptor.schema_data_class != "public"
            or descriptor.schema_trust_level != "trusted_platform"
            or not descriptor.certified_tcb_component
            or not is_certified_tcb_component(descriptor.certified_tcb_component)
        ):
            raise HostedAgenticLoopError("tool_schema_not_certified")

    def _private_state(
        self,
        *,
        context,
        request_id: str,
        state: AgenticProviderPrivateState | None,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
        egress_decisions: list[AgenticEgressDecision],
    ) -> AgenticProviderPrivateState | None:
        if state is None:
            return None
        classification = HostedContentClassification(
            state.effective_data_class,
            state.effective_trust_level,
            source_ref=f"provider-state:{state.provider_request_id or 'legacy'}",
            source_revision=state.turn_generation or "legacy",
            resource_identity=(
                f"provider-state:{context.session.session_id}:{state.provider_request_id or 'legacy'}"
            ),
            classification_revision=(1 if state.provider_request_id and state.turn_generation else None),
        )
        exported, metadata = self._evaluate(
            context=context,
            content_block_id=f"{request_id}:provider-state",
            provenance="provider_state",
            content=state.content,
            content_type=state.content_type,
            egress_policy=egress_policy,
            destination_upstream_id=destination_upstream_id,
            egress_decisions=egress_decisions,
            classification=classification,
        )
        return AgenticProviderPrivateState(
            codec_id=state.codec_id,
            codec_version=state.codec_version,
            schema_version=state.schema_version,
            content_type=state.content_type,
            content=exported,
            source_metadata=(*state.source_metadata, metadata),
            effective_data_class=classification.data_class,
            effective_trust_level=classification.trust_level,
            provider_request_id=state.provider_request_id,
            turn_generation=state.turn_generation,
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
        egress_decisions: list[AgenticEgressDecision],
        classification=None,
    ) -> tuple[bytes, AgenticSourceMetadata]:
        require_agentic_feature(
            MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
            "agentic_egress_enforcement_disabled",
        )
        classification = classification or self.classifier(context, provenance, content)
        data_attestation = None
        if classification.data_class == "workspace_internal_fake":
            if self.attestation_resolver is not None:
                try:
                    data_attestation = self.attestation_resolver(
                        context.session.workspace_id
                    )
                except Exception as error:
                    raise HostedAgenticLoopError(
                        "egress_fake_data_attestation_unavailable"
                    ) from error
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
                source_ref=str(getattr(classification, "source_ref", "") or ""),
                source_revision=str(
                    getattr(classification, "source_revision", "") or ""
                ),
                resource_identity=str(
                    getattr(classification, "resource_identity", "") or ""
                ),
                classification_revision=getattr(
                    classification,
                    "classification_revision",
                    None,
                ),
            ),
            content=content,
            destination_provider_id=context.binding.model_provider_id,
            destination_upstream_id=destination_upstream_id,
            policy=egress_policy,
            data_attestation=data_attestation,
            workspace_root=Path(context.session.workspace_root),
            persist=False,
        )
        if not result.decision.export_allowed or result.exported_content is None:
            egress_decisions.append(result.decision)
            self._commit_egress_decisions(
                workspace_id=context.session.workspace_id,
                decisions=egress_decisions,
            )
            egress_decisions.clear()
            raise HostedAgenticLoopError(result.decision.reason_code)
        egress_decisions.append(result.decision)
        source_ref = str(getattr(classification, "source_ref", "") or content_block_id)
        source_revision = str(
            getattr(classification, "source_revision", "") or context.correlation_id
        )
        resource_identity = str(
            getattr(classification, "resource_identity", "") or content_block_id
        )
        return result.exported_content, AgenticSourceMetadata(
            source_block_digest=result.decision.source_digest,
            source_data_class=classification.data_class,
            source_trust_level=classification.trust_level,
            provenance=provenance,
            source_ref=source_ref,
            source_revision=source_revision,
            resource_identity=resource_identity,
            classification_revision=getattr(classification, "classification_revision", None),
        )


def _tool_result_classification(result: AgenticToolResult) -> HostedContentClassification:
    metadata = result.source_metadata
    if metadata is None:
        fallback = fail_closed_classification(provenance="tool_result")
    else:
        fallback = validated_classification(
            data_class=metadata.source_data_class,
            provenance=metadata.provenance,
            trust_level=metadata.source_trust_level,
            source_ref=metadata.source_ref,
            source_revision=metadata.source_revision,
            source_digest=metadata.source_block_digest,
            resource_identity=metadata.resource_identity,
            classification_revision=metadata.classification_revision,
        )
    return HostedContentClassification(
        fallback.data_class,
        fallback.trust_level,
        source_ref=fallback.source_ref,
        source_revision=fallback.source_revision,
        resource_identity=fallback.resource_identity,
        classification_revision=fallback.classification_revision,
    )
