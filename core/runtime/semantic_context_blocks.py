"""Materialize instruction and governed-input semantic blocks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from core.egress.classification import CanonicalSourceClassification
from core.runtime.attachment_projection import attachment_read_encoding
from core.runtime.confined_filesystem import (
    ConfinedWorkspaceFilesystem,
    ResourceClassificationResolver,
)
from core.runtime.hosted_agentic_models import (
    HostedAgenticLoopError,
    HostedContentClassification,
    HostedContentClassifier,
)
from core.runtime.semantic_envelope_models import (
    SEMANTIC_ENVELOPE_SCHEMA_VERSION,
    SemanticEnvelopeBlock,
    canonical_classification,
    canonical_digest,
    make_semantic_block,
    platform_classification,
)
from core.runtime.workspace_instructions import (
    read_complete_confined_text,
    resolve_workspace_instruction_chain,
)


MAX_SKILL_INSTRUCTION_BYTES = 1_048_576


class SemanticContextMaterializer:
    """Materialize platform, workspace, agent, user, and skill context."""

    def __init__(
        self,
        *,
        classifier: HostedContentClassifier,
        platform_instruction: str,
        resource_classification_resolver: ResourceClassificationResolver | None,
    ) -> None:
        self.classifier = classifier
        self.platform_instruction = platform_instruction
        self.resource_classification_resolver = resource_classification_resolver

    def append_platform(self, blocks: list[SemanticEnvelopeBlock], *, context) -> None:
        blocks.append(
            make_semantic_block(
                blocks,
                context=context,
                kind="content",
                role="system",
                provenance="platform_instruction",
                content_type="text/plain",
                content=self.platform_instruction,
                classification=platform_classification(
                    "core:maverick-platform-instruction",
                    SEMANTIC_ENVELOPE_SCHEMA_VERSION,
                ),
            )
        )
        binding = context.binding
        blocks.append(
            make_semantic_block(
                blocks,
                context=context,
                kind="content",
                role="system",
                provenance="runtime_context",
                content_type="application/json",
                content={
                    "runtime_engine_id": binding.runtime_engine_id,
                    "adapter_id": binding.adapter_id,
                    "adapter_version": binding.adapter_version,
                    "model_provider_id": binding.model_provider_id,
                    "model_id": binding.model_id,
                    "provider_protocol": binding.provider_protocol,
                    "provider_api_version": binding.provider_api_version,
                    "workdir": "workspace://" + context.session.workspace_id,
                },
                classification=platform_classification(
                    f"runtime-binding:{binding.execution_binding_id}",
                    binding.binding_digest,
                ),
            )
        )
        authority = context.effective_authority
        capabilities = {
            "execution_mode": authority.execution_mode,
            "capabilities": asdict(authority.allowed_capabilities),
            "allowed_tool_handles": authority.allowed_tool_handles,
            "policy_revisions": authority.policy_revision_set,
        }
        blocks.append(
            make_semantic_block(
                blocks,
                context=context,
                kind="content",
                role="system",
                provenance="runtime_capabilities",
                content_type="application/json",
                content=capabilities,
                classification=platform_classification(
                    f"runtime-authority:{authority.execution_binding_id}",
                    canonical_digest(capabilities),
                ),
            )
        )

    def append_workspace(
        self,
        blocks: list[SemanticEnvelopeBlock],
        *,
        context,
        filesystem: ConfinedWorkspaceFilesystem,
    ) -> None:
        for instruction in resolve_workspace_instruction_chain(
            filesystem,
            workspace_root=Path(context.session.workspace_root),
            workdir=context.session.workdir,
        ):
            content = {
                "scope": instruction.scope_path,
                "path": instruction.relative_path,
                "instructions": instruction.content,
            }
            blocks.append(
                make_semantic_block(
                    blocks,
                    context=context,
                    kind="content",
                    role="developer",
                    provenance="workspace_instruction",
                    content_type="application/json",
                    content=content,
                    classification=self._file_classification(
                        context,
                        "workspace_instruction",
                        content,
                        instruction.classification,
                    ),
                    source_ref=instruction.relative_path,
                    source_revision=instruction.resource_revision,
                    resource_identity=instruction.resource_identity,
                )
            )

    def append_agent(self, blocks: list[SemanticEnvelopeBlock], *, context) -> None:
        content = context.session.system_prompt
        if content:
            source = next(
                (
                    item
                    for item in tuple(getattr(context, "input_sources", ()) or ())
                    if str(getattr(item, "provenance", "") or "")
                    == "agent_instruction"
                    and getattr(item, "content", None) == content
                    and str(getattr(item, "content_type", "") or "")
                    == "text/plain"
                    and str(getattr(item, "role", "") or "") == "developer"
                    and str(getattr(item, "source_id", "") or "")
                    == "agent-instruction"
                ),
                None,
            )
            raw_classification = getattr(source, "classification", None)
            classification = (
                canonical_classification(raw_classification)
                if isinstance(raw_classification, CanonicalSourceClassification)
                else self.classifier(context, "agent_instruction", content)
            )
            blocks.append(
                make_semantic_block(
                    blocks,
                    context=context,
                    kind="content",
                    role="developer",
                    provenance="agent_instruction",
                    content_type="text/plain",
                    content=content,
                    classification=classification,
                    source_ref=(
                        classification.source_ref
                        or str(getattr(source, "source_id", "") or "")
                    ),
                )
            )

    def append_inputs(
        self,
        blocks: list[SemanticEnvelopeBlock],
        *,
        context,
        input_text: str,
    ) -> None:
        sources = tuple(getattr(context, "input_sources", ()) or ()) or (
            _FallbackInputSource(input_text),
        )
        provenance_map = {
            "prompt": "user_input",
            "user_input": "user_input",
            "orchestration_context": "governed_context",
            "governed_context": "governed_context",
            "attachment": "attachment",
            "app_reference": "app_reference",
        }
        for source in sources:
            if str(getattr(source, "provenance", "") or "") == "agent_instruction":
                continue
            provenance = provenance_map.get(
                str(getattr(source, "provenance", "") or "")
            )
            if provenance is None:
                raise HostedAgenticLoopError("semantic_block_not_projectable")
            content = getattr(source, "content", None)
            if provenance == "attachment":
                self._validate_attachment_projection(context, source, content)
            raw_classification = getattr(source, "classification", None)
            classification = (
                canonical_classification(raw_classification)
                if isinstance(raw_classification, CanonicalSourceClassification)
                else self.classifier(context, provenance, content)
            )
            blocks.append(
                make_semantic_block(
                    blocks,
                    context=context,
                    kind="content",
                    role="user",
                    provenance=provenance,
                    content_type=str(
                        getattr(source, "content_type", "application/json")
                        or "application/json"
                    ),
                    content=content,
                    classification=classification,
                    source_ref=(
                        classification.source_ref
                        or str(getattr(source, "source_id", "") or "")
                    ),
                )
            )

    @staticmethod
    def _validate_attachment_projection(context, source, content) -> None:
        projection_mode = str(
            getattr(source, "projection_mode", "") or ""
        )
        context_policy = getattr(context.binding, "context_policy_snapshot", None)
        if (
            projection_mode != "workspace_reference"
            or not isinstance(content, dict)
            or not isinstance(content.get("projection"), dict)
            or content.get("projection")
            != {
                "mode": "workspace_reference",
                "read_capability": "core-capability:filesystem.read",
                "read_encoding": attachment_read_encoding(
                    str(content.get("media_type") or "")
                ),
            }
            or str(content.get("media_type") or "")
            != str(getattr(source, "capability_modality", "") or "")
            or not str(content.get("workspace_relative_path") or "").strip()
            or not context.effective_authority.allowed_capabilities.filesystem_read
            or "core-capability:filesystem.read"
            not in context.effective_authority.allowed_tool_handles
            or (
                context_policy is not None
                and context_policy.attachment_projection_mode
                not in {"workspace_reference", "native_or_reference"}
            )
        ):
            raise HostedAgenticLoopError("attachment_projection_not_supported")

    def append_skills(
        self,
        blocks: list[SemanticEnvelopeBlock],
        *,
        context,
        filesystem: ConfinedWorkspaceFilesystem,
    ) -> None:
        skills = tuple(getattr(context, "invoked_skills", ()) or ())
        if not skills:
            return
        workspace_root = Path(context.session.workspace_root).resolve(strict=True)
        for skill in skills:
            try:
                source_root = Path(str(getattr(skill, "source_root", ""))).resolve(
                    strict=True
                )
                skill_path = (
                    source_root.relative_to(workspace_root) / "SKILL.md"
                ).as_posix()
                if source_root.is_symlink() or (source_root / "SKILL.md").is_symlink():
                    raise ValueError
                result = read_complete_confined_text(
                    filesystem,
                    skill_path,
                    max_bytes=MAX_SKILL_INSTRUCTION_BYTES,
                )
            except Exception as error:
                raise HostedAgenticLoopError("skill_materialization_failed") from error
            content = {
                "skill_id": str(getattr(skill, "skill_id", "")),
                "name": str(getattr(skill, "name", "")),
                "description": str(getattr(skill, "description", "")),
                "owner_kind": str(getattr(skill, "owner_kind", "")),
                "owner_id": str(getattr(skill, "owner_id", "")),
                "instructions": str(result.payload["content"]),
            }
            blocks.append(
                make_semantic_block(
                    blocks,
                    context=context,
                    kind="content",
                    role="developer",
                    provenance="skill_fragment",
                    content_type="application/json",
                    content=content,
                    classification=self._file_classification(
                        context,
                        "skill_fragment",
                        content,
                        result.classification,
                    ),
                    source_ref=skill_path,
                    source_revision=str(result.payload["resource_revision"]),
                    resource_identity=str(result.payload["resource_identity"]),
                )
            )

    def _file_classification(
        self,
        context,
        provenance: str,
        content: object,
        classification: CanonicalSourceClassification,
    ) -> HostedContentClassification:
        if self.resource_classification_resolver is None:
            return self.classifier(context, provenance, content)
        return canonical_classification(classification)


@dataclass(frozen=True)
class _FallbackInputSource:
    content: str
    source_id: str = "turn-user-input"
    provenance: str = "user_input"
    content_type: str = "text/plain"
