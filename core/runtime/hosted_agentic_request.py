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
from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticProviderPrivateState,
    AgenticRequestPhase,
    AgenticRequestContentBlock,
    AgenticSourceMetadata,
    AgenticToolDefinition,
    AgenticToolResult,
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
from core.runtime.semantic_envelope import (
    HostedSemanticEnvelopeCompiler,
    SemanticEnvelopeBlock,
    semantic_projection_digest,
)
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
    tool_handles: tuple[str, ...] = ()


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
        "context_policy_revision": request.context_policy_revision,
        "context_compaction_evidence_digest": (
            request.context_compaction_evidence_digest
        ),
        "context_compaction_applied": request.context_compaction_applied,
        "endpoint_capability_snapshot_digest": (
            request.endpoint_capability_snapshot_digest
        ),
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
        semantic_compiler: HostedSemanticEnvelopeCompiler | None = None,
        classification_revalidator: Callable[
            [object, HostedContentClassification],
            HostedContentClassification,
        ]
        | None = None,
    ) -> None:
        self.egress_evaluator = egress_evaluator
        self.classifier = classifier
        self.attestation_resolver = attestation_resolver
        self.classification_revalidator = classification_revalidator
        self.semantic_compiler = semantic_compiler or HostedSemanticEnvelopeCompiler(
            classifier=classifier,
            platform_instruction=HOSTED_TOOL_USE_INSTRUCTION,
            classification_revalidator=classification_revalidator,
        )

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
        context_policy_revision: str = "",
        context_compaction_evidence_digest: str = "",
        context_compaction_applied: bool = False,
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
                context_policy_revision=context_policy_revision,
                context_compaction_evidence_digest=(
                    context_compaction_evidence_digest
                ),
                context_compaction_applied=context_compaction_applied,
            ),
            context=context,
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
        context_policy_revision: str = "",
        context_compaction_evidence_digest: str = "",
        context_compaction_applied: bool = False,
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
        envelope = self.semantic_compiler.compile(
            context=context,
            input_text=input_text,
            catalog=catalog,
            tool_results=tool_results,
            provider_private_state=provider_private_state,
            request_phase=request_phase,
        )
        egress_decisions: list[AgenticEgressDecision] = []
        semantic_content = tuple(
            block for block in envelope.blocks if block.kind == "content"
        )
        semantic_tools = tuple(
            block for block in envelope.blocks if block.kind == "tool_schema"
        )
        semantic_results = tuple(
            block for block in envelope.blocks if block.kind == "tool_result"
        )
        semantic_state = tuple(
            block for block in envelope.blocks if block.kind == "provider_state"
        )
        if (
            len(semantic_tools) != len(catalog.descriptors)
            or len(semantic_results) != len(tool_results)
            or len(semantic_state) != (1 if provider_private_state is not None else 0)
        ):
            raise HostedAgenticLoopError("semantic_envelope_incomplete")
        content_blocks = [
            self._content_block(
                context=context,
                request_id=request_id,
                index=index,
                role=block.role,
                provenance=block.provenance,
                content=block.content,
                content_type=block.content_type,
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
                egress_decisions=egress_decisions,
                classification=_semantic_classification(block),
                semantic_block=block,
            )
            for index, block in enumerate(semantic_content)
        ]
        tools = tuple(
            self._tool_definition(
                context=context,
                request_id=request_id,
                index=index,
                descriptor=descriptor,
                semantic_block=semantic_tools[index],
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
            semantic_block=(semantic_state[0] if semantic_state else None),
        )
        approved_tool_results = tuple(
            self._request_tool_result(
                context=context,
                request_id=request_id,
                result=result,
                semantic_block=semantic_results[index],
                egress_policy=egress_policy,
                destination_upstream_id=destination_upstream_id,
                egress_decisions=egress_decisions,
            )
            for index, result in enumerate(tool_results)
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
        projected_ids = tuple(
            metadata.semantic_block_id for metadata in source_metadata
        )
        expected_ids = tuple(block.block_id for block in envelope.blocks)
        if projected_ids != expected_ids:
            raise HostedAgenticLoopError("semantic_block_not_projectable")
        projection_digest = semantic_projection_digest(
            source_snapshot_digest=envelope.source_snapshot_digest,
            compiler_id=self.semantic_compiler.compiler_id,
            compiler_revision=self.semantic_compiler.compiler_revision,
            projected_metadata=source_metadata,
            projection_contract={
                "provider_id": binding.model_provider_id,
                "model_id": binding.model_id,
                "model_revision": getattr(binding, "model_revision", None),
                "model_revision_policy": getattr(
                    binding,
                    "model_revision_policy",
                    "provider_alias",
                ),
                "provider_protocol": binding.provider_protocol,
                "provider_api_version": binding.provider_api_version,
                "request_phase": request_phase,
                "context_policy_revision": context_policy_revision,
                "context_compaction_evidence_digest": (
                    context_compaction_evidence_digest
                ),
                "context_compaction_applied": context_compaction_applied,
                "content": [
                    {
                        "semantic_block_id": block.source_metadata.semantic_block_id,
                        "role": block.role,
                        "provenance": block.provenance,
                        "content_type": block.content_type,
                    }
                    for block in content_blocks
                    if block.source_metadata is not None
                ],
                "tools": [
                    {
                        "semantic_block_id": tool.source_metadata.semantic_block_id,
                        "name": tool.name,
                    }
                    for tool in tools
                    if tool.source_metadata is not None
                ],
                "tool_results": [
                    {
                        "semantic_block_id": result.source_metadata.semantic_block_id,
                        "call_id": result.provider_tool_call_id,
                        "name": result.provider_tool_name,
                        "content_type": result.content_type,
                        "is_error": result.is_error,
                    }
                    for result in approved_tool_results
                    if result.source_metadata is not None
                ],
                "provider_state": (
                    None
                    if private_state is None
                    else {
                        "semantic_block_id": (
                            private_state.source_metadata[0].semantic_block_id
                        ),
                        "codec_id": private_state.codec_id,
                        "codec_version": private_state.codec_version,
                        "schema_version": private_state.schema_version,
                        "content_type": private_state.content_type,
                    }
                ),
            },
        )
        request = AgenticModelRequest(
            schema_version="1",
            request_id=request_id,
            correlation_id=context.correlation_id,
            model_id=binding.model_id,
            model_revision=getattr(binding, "model_revision", None),
            model_revision_policy=getattr(
                binding,
                "model_revision_policy",
                "provider_alias",
            ),
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
            semantic_envelope_schema_version=envelope.schema_version,
            semantic_source_snapshot_digest=envelope.source_snapshot_digest,
            semantic_projection_compiler_id=self.semantic_compiler.compiler_id,
            semantic_projection_compiler_revision=(
                self.semantic_compiler.compiler_revision
            ),
            provider_egress_projection_digest=projection_digest,
            context_policy_revision=context_policy_revision,
            context_compaction_evidence_digest=(
                context_compaction_evidence_digest
            ),
            context_compaction_applied=context_compaction_applied,
        )
        return HostedAgenticPreparedRequest(
            request=request,
            workspace_id=context.session.workspace_id,
            egress_decisions=tuple(egress_decisions),
            tool_handles=tuple(
                descriptor.handle for descriptor in catalog.descriptors
            ),
        )

    def commit(
        self,
        prepared: HostedAgenticPreparedRequest,
        *,
        context=None,
    ) -> AgenticModelRequest:
        """Revalidate and commit only after request-specific preflight eligibility."""
        self.revalidate_for_transport(prepared, context=context)
        self._commit_egress_decisions(
            workspace_id=prepared.workspace_id,
            decisions=prepared.egress_decisions,
        )
        return prepared.request

    def revalidate_for_transport(
        self,
        prepared: HostedAgenticPreparedRequest,
        *,
        context,
    ) -> None:
        """Recheck request authority at the last boundary before transport."""
        if context is None:
            raise HostedAgenticLoopError("runtime_authority_unavailable")
        self._validate_context_capabilities(context)
        authority = getattr(context, "effective_authority", None)
        if authority is None:
            raise HostedAgenticLoopError("runtime_authority_unavailable")
        if any(
            handle not in authority.allowed_tool_handles
            for handle in prepared.tool_handles
        ):
            raise HostedAgenticLoopError("tool_not_authorized")
        if any(
            metadata.source_data_class
            not in authority.allowed_remote_data_classes
            for metadata in prepared.request.source_metadata
        ):
            raise HostedAgenticLoopError("egress_data_class_denied")
        if self.classification_revalidator is None:
            if any(
                _metadata_requires_live_authority(metadata)
                for metadata in prepared.request.source_metadata
            ):
                raise HostedAgenticLoopError(
                    "classification_authority_unavailable"
                )
            return
        for metadata in prepared.request.source_metadata:
            snapshot = _metadata_classification(metadata)
            try:
                current = self.classification_revalidator(context, snapshot)
            except Exception as error:
                raise HostedAgenticLoopError(
                    "classification_authority_unavailable"
                ) from error
            if not _same_transport_classification(snapshot, current):
                raise HostedAgenticLoopError("egress_data_class_denied")

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
        semantic_block: SemanticEnvelopeBlock | None = None,
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
            semantic_block=semantic_block,
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
        semantic_block: SemanticEnvelopeBlock,
        egress_policy: AgenticEgressPolicy,
        destination_upstream_id: str | None,
        egress_decisions: list[AgenticEgressDecision],
    ) -> AgenticToolResult:
        classification = _semantic_classification(semantic_block)
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
            semantic_block=semantic_block,
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
        semantic_block: SemanticEnvelopeBlock,
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
        classification = _semantic_classification(semantic_block)
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
            semantic_block=semantic_block,
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
        semantic_block: SemanticEnvelopeBlock | None,
    ) -> AgenticProviderPrivateState | None:
        if state is None:
            return None
        if semantic_block is None:
            raise HostedAgenticLoopError("semantic_envelope_incomplete")
        classification = _semantic_classification(semantic_block)
        classification = self._revalidate_provider_state_sources(
            context,
            state,
            classification,
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
            semantic_block=semantic_block,
        )
        return AgenticProviderPrivateState(
            codec_id=state.codec_id,
            codec_version=state.codec_version,
            schema_version=state.schema_version,
            content_type=state.content_type,
            content=exported,
            source_metadata=(metadata,),
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
        semantic_block: SemanticEnvelopeBlock | None = None,
    ) -> tuple[bytes, AgenticSourceMetadata]:
        require_agentic_feature(
            MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
            "agentic_egress_enforcement_disabled",
        )
        classification = classification or self.classifier(context, provenance, content)
        if self.classification_revalidator is not None:
            try:
                classification = self.classification_revalidator(
                    context,
                    classification,
                )
            except Exception as error:
                raise HostedAgenticLoopError(
                    "classification_authority_unavailable"
                ) from error
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
                classification_authority_id=str(
                    getattr(
                        classification,
                        "classification_authority_id",
                        "",
                    )
                    or ""
                ),
                classification_authority_kind=str(
                    getattr(
                        classification,
                        "classification_authority_kind",
                        "",
                    )
                    or ""
                ),
                classification_authority_ref=str(
                    getattr(
                        classification,
                        "classification_authority_ref",
                        "",
                    )
                    or ""
                ),
                classification_authority_revision=getattr(
                    classification,
                    "classification_authority_revision",
                    None,
                ),
                classification_authority_digest=str(
                    getattr(
                        classification,
                        "classification_authority_digest",
                        "",
                    )
                    or ""
                ),
                classification_authority_policy_revision=str(
                    getattr(
                        classification,
                        "classification_authority_policy_revision",
                        "",
                    )
                    or ""
                ),
                classification_authority_bound=getattr(
                    classification,
                    "classification_authority_bound",
                    False,
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
            classification_authority_id=str(
                getattr(classification, "classification_authority_id", "") or ""
            ),
            classification_authority_kind=str(
                getattr(classification, "classification_authority_kind", "") or ""
            ),
            classification_authority_ref=str(
                getattr(classification, "classification_authority_ref", "") or ""
            ),
            classification_authority_revision=getattr(
                classification,
                "classification_authority_revision",
                None,
            ),
            classification_authority_digest=str(
                getattr(classification, "classification_authority_digest", "")
                or ""
            ),
            classification_authority_policy_revision=str(
                getattr(
                    classification,
                    "classification_authority_policy_revision",
                    "",
                )
                or ""
            ),
            classification_authority_bound=getattr(
                classification,
                "classification_authority_bound",
                False,
            ),
            semantic_block_id=(
                "" if semantic_block is None else semantic_block.block_id
            ),
            semantic_block_schema_version=(
                "" if semantic_block is None else semantic_block.schema_version
            ),
            semantic_source_digest=(
                "" if semantic_block is None else semantic_block.source_digest
            ),
            egress_decision_id=result.decision.decision_id,
            transformation=result.decision.transformation,
            exported_digest=str(result.decision.exported_digest or ""),
        )

    def _revalidate_provider_state_sources(
        self,
        context,
        state: AgenticProviderPrivateState,
        classification: HostedContentClassification,
    ) -> HostedContentClassification:
        if self.classification_revalidator is None:
            return classification
        if not state.source_metadata:
            return HostedContentClassification(
                "unclassified",
                "untrusted_external",
                source_ref=classification.source_ref,
                source_revision=classification.source_revision,
                resource_identity=classification.resource_identity,
                classification_revision=None,
                content_digest=classification.content_digest,
                classification_authority_bound=None,
            )
        for metadata in state.source_metadata:
            source = _metadata_classification(metadata)
            try:
                live = self.classification_revalidator(context, source)
            except Exception as error:
                raise HostedAgenticLoopError(
                    "classification_authority_unavailable"
                ) from error
            if live.data_class == "unclassified":
                return HostedContentClassification(
                    "unclassified",
                    "untrusted_external",
                    source_ref=classification.source_ref,
                    source_revision=classification.source_revision,
                    resource_identity=classification.resource_identity,
                    classification_revision=None,
                    content_digest=classification.content_digest,
                    classification_authority_bound=None,
                )
        return classification


def _semantic_classification(
    block: SemanticEnvelopeBlock,
) -> HostedContentClassification:
    return HostedContentClassification(
        block.data_class,  # type: ignore[arg-type]
        block.trust_level,
        source_ref=block.source_ref,
        source_revision=block.source_revision,
        resource_identity=block.resource_identity,
        classification_revision=block.classification_revision,
        content_digest=block.source_digest,
        classification_authority_id=block.classification_authority_id,
        classification_authority_kind=block.classification_authority_kind,
        classification_authority_ref=block.classification_authority_ref,
        classification_authority_revision=(
            block.classification_authority_revision
        ),
        classification_authority_digest=block.classification_authority_digest,
        classification_authority_policy_revision=(
            block.classification_authority_policy_revision
        ),
        classification_authority_bound=block.classification_authority_bound,
    )


def _metadata_classification(
    metadata: AgenticSourceMetadata,
) -> HostedContentClassification:
    return HostedContentClassification(
        metadata.source_data_class,
        metadata.source_trust_level,
        source_ref=metadata.source_ref,
        source_revision=metadata.source_revision,
        resource_identity=metadata.resource_identity,
        classification_revision=metadata.classification_revision,
        content_digest=metadata.source_block_digest,
        classification_authority_id=metadata.classification_authority_id,
        classification_authority_kind=metadata.classification_authority_kind,
        classification_authority_ref=metadata.classification_authority_ref,
        classification_authority_revision=(
            metadata.classification_authority_revision
        ),
        classification_authority_digest=(
            metadata.classification_authority_digest
        ),
        classification_authority_policy_revision=(
            metadata.classification_authority_policy_revision
        ),
        classification_authority_bound=(
            metadata.classification_authority_bound
        ),
    )


def _same_transport_classification(left, right) -> bool:
    """Require the exact authority-bearing classification prepared for egress."""
    fields = (
        "data_class",
        "trust_level",
        "source_ref",
        "source_revision",
        "resource_identity",
        "classification_revision",
        "content_digest",
        "classification_authority_id",
        "classification_authority_kind",
        "classification_authority_ref",
        "classification_authority_revision",
        "classification_authority_digest",
        "classification_authority_policy_revision",
        "classification_authority_bound",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _metadata_requires_live_authority(metadata: AgenticSourceMetadata) -> bool:
    return bool(
        metadata.classification_authority_bound is not False
        or metadata.classification_authority_id
        or metadata.classification_authority_kind
        or metadata.classification_authority_ref
        or metadata.classification_authority_revision is not None
        or metadata.classification_authority_digest
        or metadata.classification_authority_policy_revision
    )
