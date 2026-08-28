"""Store adapters for provider-domain control-plane records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from core.providers.agentic_models import (
    AgenticContextPolicy,
    ActorSelectionPolicy,
    AgenticMigrationRecord,
    AgenticProfileDefinition,
    AgenticProfileDefinitionStatus,
    AgenticRuntimePolicy,
    RoutingConstraint,
    WorkspaceAgenticProfileBinding,
)
from core.providers.capability_models import (
    CapabilityCertificate,
    CapabilityCertificateStatus,
    CapabilityEvidenceRecord,
    RuntimeCapabilitySet,
)
from core.providers.errors import (
    AgenticProfileConflictError,
    CapabilityCertificateConflictError,
    ProviderCredentialBindingError,
    ProviderNotFoundError,
)
from core.providers.models import (
    ProviderCapabilitySet,
    ProviderCredentialBinding,
    ProviderCredentialRequirement,
    ProviderDefinition,
    ProviderExecutionContract,
    ProviderHostedSelection,
    ProviderModelOption,
    ProviderNetworkRequirement,
    ProviderReasoningOption,
    ProviderSelection,
    ProviderSpeechSelection,
)
from core.shared.in_memory_collection import InMemoryCollection


class DocumentCollection(Protocol):
    """Minimal collection protocol used by provider stores."""

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]] | Any:
        ...

    def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> Any:
        ...

    def insert_one_if_absent(self, query: dict[str, Any], document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        ...

    def compare_and_set(self, query: dict[str, Any], update: dict[str, Any]) -> bool:
        ...


class ProviderStore(Protocol):
    """Persistence contract for provider definitions, bindings, and selection."""

    def save_provider_definition(self, record: ProviderDefinition) -> ProviderDefinition:
        ...

    def get_provider_definition(self, provider_id: str) -> ProviderDefinition:
        ...

    def list_provider_definitions(self) -> list[ProviderDefinition]:
        ...

    def save_provider_binding(self, record: ProviderCredentialBinding) -> ProviderCredentialBinding:
        ...

    def get_provider_binding(self, binding_id: str) -> ProviderCredentialBinding:
        ...

    def list_provider_bindings(
        self,
        *,
        workspace_id: str | None = None,
        provider_id: str | None = None,
    ) -> list[ProviderCredentialBinding]:
        ...

    def save_provider_selection(self, record: ProviderSelection) -> ProviderSelection:
        ...

    def get_provider_selection(self, workspace_id: str) -> ProviderSelection | None:
        ...

    def list_provider_selections(self) -> list[ProviderSelection]:
        ...

    def save_hosted_provider_selection(self, record: ProviderHostedSelection) -> ProviderHostedSelection:
        ...

    def get_hosted_provider_selection(self, *, workspace_id: str, profile: str) -> ProviderHostedSelection | None:
        ...

    def save_speech_provider_selection(self, record: ProviderSpeechSelection) -> ProviderSpeechSelection:
        ...

    def get_speech_provider_selection(self, *, workspace_id: str, profile: str) -> ProviderSpeechSelection | None:
        ...

    def save_agentic_profile_definition(self, record: AgenticProfileDefinition) -> AgenticProfileDefinition:
        ...

    def get_agentic_profile_definition(self, definition_id: str, revision: str) -> AgenticProfileDefinition:
        ...

    def list_agentic_profile_definitions(self) -> list[AgenticProfileDefinition]:
        ...

    def save_agentic_profile_definition_status(
        self,
        record: AgenticProfileDefinitionStatus,
        *,
        expected_revision: int | None,
    ) -> AgenticProfileDefinitionStatus:
        ...

    def get_agentic_profile_definition_status(
        self,
        definition_id: str,
        definition_revision: str,
    ) -> AgenticProfileDefinitionStatus | None:
        ...

    def save_workspace_agentic_profile_binding(
        self,
        record: WorkspaceAgenticProfileBinding,
        *,
        expected_revision: int | None,
    ) -> WorkspaceAgenticProfileBinding:
        ...

    def get_workspace_agentic_profile_binding(self, binding_id: str) -> WorkspaceAgenticProfileBinding:
        ...

    def list_workspace_agentic_profile_bindings(self, workspace_id: str) -> list[WorkspaceAgenticProfileBinding]:
        ...

    def list_all_workspace_agentic_profile_bindings(self) -> list[WorkspaceAgenticProfileBinding]:
        ...

    def save_agentic_migration(self, record: AgenticMigrationRecord) -> AgenticMigrationRecord:
        ...

    def get_agentic_migration(self, migration_id: str) -> AgenticMigrationRecord | None:
        ...

    def save_capability_evidence(self, record: CapabilityEvidenceRecord) -> CapabilityEvidenceRecord:
        ...

    def get_capability_evidence(self, evidence_digest: str) -> CapabilityEvidenceRecord:
        ...

    def save_capability_certificate(self, record: CapabilityCertificate) -> CapabilityCertificate:
        ...

    def get_capability_certificate(self, certificate_id: str) -> CapabilityCertificate:
        ...

    def list_capability_certificates(self) -> list[CapabilityCertificate]:
        ...

    def save_capability_certificate_status(
        self,
        record: CapabilityCertificateStatus,
        *,
        expected_revision: int | None,
    ) -> CapabilityCertificateStatus:
        ...

    def get_capability_certificate_status(
        self,
        certificate_id: str,
    ) -> CapabilityCertificateStatus | None:
        ...


@dataclass(frozen=True)
class ProviderCollections:
    """Collection bundle for provider persistence."""

    definitions: DocumentCollection
    bindings: DocumentCollection
    selections: DocumentCollection
    hosted_selections: DocumentCollection | None = None
    speech_selections: DocumentCollection | None = None
    agentic_profile_definitions: DocumentCollection | None = None
    agentic_profile_definition_statuses: DocumentCollection | None = None
    workspace_agentic_profile_bindings: DocumentCollection | None = None
    agentic_migrations: DocumentCollection | None = None
    capability_evidence: DocumentCollection | None = None
    capability_certificates: DocumentCollection | None = None
    capability_certificate_statuses: DocumentCollection | None = None


class ProviderDocumentStore:
    """Persist provider-domain records in document collections."""

    def __init__(self, collections: ProviderCollections) -> None:
        self.collections = collections
        self._hosted_selections = collections.hosted_selections or InMemoryCollection()
        self._speech_selections = collections.speech_selections or InMemoryCollection()
        self._agentic_profile_definitions = collections.agentic_profile_definitions or InMemoryCollection()
        self._agentic_profile_definition_statuses = (
            collections.agentic_profile_definition_statuses or InMemoryCollection()
        )
        self._workspace_agentic_profile_bindings = (
            collections.workspace_agentic_profile_bindings or InMemoryCollection()
        )
        self._agentic_migrations = collections.agentic_migrations or InMemoryCollection()
        self._capability_evidence = collections.capability_evidence or InMemoryCollection()
        self._capability_certificates = collections.capability_certificates or InMemoryCollection()
        self._capability_certificate_statuses = (
            collections.capability_certificate_statuses or InMemoryCollection()
        )

    def _provider_definition(self, document: dict[str, Any]) -> ProviderDefinition:
        payload = dict(document)
        if "provider_role" not in payload:
            payload["provider_role"] = "runtime_engine" if payload.get("kind") == "runtime_backend" else "model_provider"
        payload["capabilities"] = ProviderCapabilitySet(**payload["capabilities"])
        payload["model_options"] = [
            self._provider_model_option(item)
            for item in payload.get("model_options", [])
            if isinstance(item, dict)
        ]
        payload["credential_requirements"] = [
            ProviderCredentialRequirement(**item)
            for item in payload.get("credential_requirements", [])
            if isinstance(item, dict)
        ]
        payload["network_requirements"] = [
            ProviderNetworkRequirement(**item)
            for item in payload.get("network_requirements", [])
            if isinstance(item, dict)
        ]
        execution_contract = payload.get("execution_contract")
        if isinstance(execution_contract, dict):
            payload["execution_contract"] = ProviderExecutionContract(**execution_contract)
        return ProviderDefinition(**payload)

    def _provider_model_option(self, document: dict[str, Any]) -> ProviderModelOption:
        payload = dict(document)
        payload["supported_reasoning_efforts"] = [
            ProviderReasoningOption(**item)
            for item in payload.get("supported_reasoning_efforts", [])
            if isinstance(item, dict)
        ]
        return ProviderModelOption(**payload)

    def save_provider_definition(self, record: ProviderDefinition) -> ProviderDefinition:
        self.collections.definitions.update_one(
            {"provider_id": record.provider_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_provider_definition(self, provider_id: str) -> ProviderDefinition:
        document = self.collections.definitions.find_one({"provider_id": provider_id})
        if document is None:
            raise ProviderNotFoundError(f"Provider `{provider_id}` was not found.")
        return self._provider_definition(document)

    def list_provider_definitions(self) -> list[ProviderDefinition]:
        return [self._provider_definition(document) for document in self.collections.definitions.find({})]

    def save_provider_binding(self, record: ProviderCredentialBinding) -> ProviderCredentialBinding:
        self.collections.bindings.update_one(
            {"binding_id": record.binding_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_provider_binding(self, binding_id: str) -> ProviderCredentialBinding:
        document = self.collections.bindings.find_one({"binding_id": binding_id})
        if document is None:
            raise ProviderCredentialBindingError(f"Provider binding `{binding_id}` was not found.")
        return ProviderCredentialBinding(**document)

    def list_provider_bindings(
        self,
        *,
        workspace_id: str | None = None,
        provider_id: str | None = None,
    ) -> list[ProviderCredentialBinding]:
        query: dict[str, Any] = {}
        if workspace_id is not None:
            query["workspace_id"] = workspace_id
        if provider_id is not None:
            query["provider_id"] = provider_id
        return [ProviderCredentialBinding(**document) for document in self.collections.bindings.find(query)]

    def save_provider_selection(self, record: ProviderSelection) -> ProviderSelection:
        self.collections.selections.update_one(
            {"workspace_id": record.workspace_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_provider_selection(self, workspace_id: str) -> ProviderSelection | None:
        document = self.collections.selections.find_one({"workspace_id": workspace_id})
        if document is None:
            return None
        return ProviderSelection(**document)

    def list_provider_selections(self) -> list[ProviderSelection]:
        return [ProviderSelection(**document) for document in self.collections.selections.find({})]

    def save_hosted_provider_selection(self, record: ProviderHostedSelection) -> ProviderHostedSelection:
        self._hosted_selections.update_one(
            {"workspace_id": record.workspace_id, "profile": record.profile},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_hosted_provider_selection(self, *, workspace_id: str, profile: str) -> ProviderHostedSelection | None:
        document = self._hosted_selections.find_one({"workspace_id": workspace_id, "profile": profile})
        if document is None:
            return None
        return ProviderHostedSelection(**document)

    def save_speech_provider_selection(self, record: ProviderSpeechSelection) -> ProviderSpeechSelection:
        self._speech_selections.update_one(
            {"workspace_id": record.workspace_id, "profile": record.profile},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_speech_provider_selection(self, *, workspace_id: str, profile: str) -> ProviderSpeechSelection | None:
        document = self._speech_selections.find_one({"workspace_id": workspace_id, "profile": profile})
        if document is None:
            return None
        return ProviderSpeechSelection(**document)

    def save_agentic_profile_definition(self, record: AgenticProfileDefinition) -> AgenticProfileDefinition:
        identity = {"definition_id": record.definition_id, "revision": record.revision}
        payload = asdict(record)
        existing, inserted = self._agentic_profile_definitions.insert_one_if_absent(identity, payload)
        if not inserted and existing != payload:
            raise AgenticProfileConflictError(
                f"Agentic profile definition `{record.definition_id}` revision `{record.revision}` is immutable."
            )
        return record

    def get_agentic_profile_definition(self, definition_id: str, revision: str) -> AgenticProfileDefinition:
        document = self._agentic_profile_definitions.find_one(
            {"definition_id": definition_id, "revision": revision}
        )
        if document is None:
            raise ProviderNotFoundError(
                f"Agentic profile definition `{definition_id}` revision `{revision}` was not found."
            )
        return _agentic_profile_definition(document)

    def list_agentic_profile_definitions(self) -> list[AgenticProfileDefinition]:
        return [_agentic_profile_definition(item) for item in self._agentic_profile_definitions.find({})]

    def save_agentic_profile_definition_status(
        self,
        record: AgenticProfileDefinitionStatus,
        *,
        expected_revision: int | None,
    ) -> AgenticProfileDefinitionStatus:
        identity = {
            "definition_id": record.definition_id,
            "definition_revision": record.definition_revision,
        }
        _save_revisioned_record(
            self._agentic_profile_definition_statuses,
            identity=identity,
            payload=asdict(record),
            expected_revision=expected_revision,
            label="Agentic profile definition status",
        )
        return record

    def get_agentic_profile_definition_status(
        self,
        definition_id: str,
        definition_revision: str,
    ) -> AgenticProfileDefinitionStatus | None:
        document = self._agentic_profile_definition_statuses.find_one(
            {"definition_id": definition_id, "definition_revision": definition_revision}
        )
        return None if document is None else AgenticProfileDefinitionStatus(**document)

    def save_workspace_agentic_profile_binding(
        self,
        record: WorkspaceAgenticProfileBinding,
        *,
        expected_revision: int | None,
    ) -> WorkspaceAgenticProfileBinding:
        _save_revisioned_record(
            self._workspace_agentic_profile_bindings,
            identity={"binding_id": record.binding_id, "workspace_id": record.workspace_id},
            payload=asdict(record),
            expected_revision=expected_revision,
            label="Workspace agentic profile binding",
        )
        return record

    def get_workspace_agentic_profile_binding(self, binding_id: str) -> WorkspaceAgenticProfileBinding:
        document = self._workspace_agentic_profile_bindings.find_one({"binding_id": binding_id})
        if document is None:
            raise ProviderNotFoundError(f"Workspace agentic profile binding `{binding_id}` was not found.")
        return _workspace_agentic_profile_binding(document)

    def list_workspace_agentic_profile_bindings(self, workspace_id: str) -> list[WorkspaceAgenticProfileBinding]:
        return [
            _workspace_agentic_profile_binding(item)
            for item in self._workspace_agentic_profile_bindings.find({"workspace_id": workspace_id})
        ]

    def list_all_workspace_agentic_profile_bindings(self) -> list[WorkspaceAgenticProfileBinding]:
        """List every workspace binding through the configured document adapter."""
        return [
            _workspace_agentic_profile_binding(item)
            for item in self._workspace_agentic_profile_bindings.find({})
        ]

    def save_agentic_migration(self, record: AgenticMigrationRecord) -> AgenticMigrationRecord:
        self._agentic_migrations.update_one(
            {"migration_id": record.migration_id},
            {"$set": asdict(record)},
            upsert=True,
        )
        return record

    def get_agentic_migration(self, migration_id: str) -> AgenticMigrationRecord | None:
        document = self._agentic_migrations.find_one({"migration_id": migration_id})
        return None if document is None else AgenticMigrationRecord(**document)

    def save_capability_evidence(self, record: CapabilityEvidenceRecord) -> CapabilityEvidenceRecord:
        existing, inserted = self._capability_evidence.insert_one_if_absent(
            {"evidence_digest": record.evidence_digest},
            asdict(record),
        )
        if not inserted and existing != asdict(record):
            raise CapabilityCertificateConflictError("certificate_evidence_immutable_conflict")
        return record

    def get_capability_evidence(self, evidence_digest: str) -> CapabilityEvidenceRecord:
        document = self._capability_evidence.find_one({"evidence_digest": evidence_digest})
        if document is None:
            raise ProviderNotFoundError(f"Capability evidence `{evidence_digest}` was not found.")
        payload = dict(document)
        payload["evidence_refs"] = tuple(payload.get("evidence_refs", ()))
        for field_name in (
            "tcb_manifest_id",
            "tcb_manifest_version",
            "tcb_structure_digest",
            "tcb_live_digest",
        ):
            payload.setdefault(field_name, "")
        return CapabilityEvidenceRecord(**payload)

    def save_capability_certificate(self, record: CapabilityCertificate) -> CapabilityCertificate:
        existing, inserted = self._capability_certificates.insert_one_if_absent(
            {"certificate_id": record.certificate_id},
            asdict(record),
        )
        if not inserted and existing != asdict(record):
            raise CapabilityCertificateConflictError("certificate_immutable_conflict")
        return record

    def get_capability_certificate(self, certificate_id: str) -> CapabilityCertificate:
        document = self._capability_certificates.find_one({"certificate_id": certificate_id})
        if document is None:
            raise ProviderNotFoundError(f"Capability certificate `{certificate_id}` was not found.")
        return _capability_certificate(document)

    def list_capability_certificates(self) -> list[CapabilityCertificate]:
        return [_capability_certificate(item) for item in self._capability_certificates.find({})]

    def save_capability_certificate_status(
        self,
        record: CapabilityCertificateStatus,
        *,
        expected_revision: int | None,
    ) -> CapabilityCertificateStatus:
        current_document = self._capability_certificate_statuses.find_one(
            {"certificate_id": record.certificate_id}
        )
        if record.status == "active" and (record.revoked_at is not None or record.revocation_reason is not None):
            raise CapabilityCertificateConflictError("certificate_status_invalid")
        if record.status == "revoked" and (record.revoked_at is None or not record.revocation_reason):
            raise CapabilityCertificateConflictError("certificate_status_invalid")
        if current_document is not None and current_document.get("status") == "revoked" and record.status != "revoked":
            raise CapabilityCertificateConflictError("certificate_revocation_is_permanent")
        try:
            _save_revisioned_record(
                self._capability_certificate_statuses,
                identity={"certificate_id": record.certificate_id},
                payload=asdict(record),
                expected_revision=expected_revision,
                label="Capability certificate status",
            )
        except AgenticProfileConflictError as error:
            raise CapabilityCertificateConflictError("certificate_status_revision_conflict") from error
        return record

    def get_capability_certificate_status(
        self,
        certificate_id: str,
    ) -> CapabilityCertificateStatus | None:
        document = self._capability_certificate_statuses.find_one({"certificate_id": certificate_id})
        return None if document is None else CapabilityCertificateStatus(**document)


def _agentic_profile_definition(document: dict[str, Any]) -> AgenticProfileDefinition:
    payload = dict(document)
    payload.setdefault("full_workspace_contract_revision", "")
    for field_name in (
        "execution_family",
        "harness_recipe_id",
        "harness_recipe_revision",
        "harness_recipe_digest",
        "provider_capability_catalog_digest",
        "semantic_projection_compiler_revision",
        "tool_contract_revision",
    ):
        payload.setdefault(field_name, "")
    payload["context_policy"] = _agentic_context_policy(
        payload.get("context_policy")
    )
    _migrate_legacy_agentic_profile_egress(payload)
    payload["routing_constraint"] = _routing_constraint(payload["routing_constraint"])
    payload["policy_ceiling"] = _agentic_runtime_policy(payload["policy_ceiling"])
    return AgenticProfileDefinition(**payload)


def _migrate_legacy_agentic_profile_egress(payload: dict[str, Any]) -> None:
    """Project pre-egress-metadata definitions during the bounded schema migration."""
    if "egress_policy_id" in payload and "egress_policy_revision" in payload:
        return
    if payload.get("provider_protocol") == "codex-app-server-stdio":
        payload["egress_policy_id"] = "local-runtime-no-remote-egress"
        payload["egress_policy_revision"] = "1"
    else:
        payload["egress_policy_id"] = "remote-agentic-contained"
        payload["egress_policy_revision"] = "2"


def _capability_certificate(document: dict[str, Any]) -> CapabilityCertificate:
    payload = dict(document)
    payload["certified_upstream_ids"] = tuple(payload.get("certified_upstream_ids", ()))
    payload["certified_reasoning_efforts"] = tuple(
        payload.get("certified_reasoning_efforts", ())
    )
    payload.setdefault("default_reasoning_effort", None)
    payload["evidence_refs"] = tuple(payload.get("evidence_refs", ()))
    capabilities = dict(payload["certified_capabilities"])
    capabilities.setdefault("filesystem_list", False)
    capabilities.setdefault("app_references", False)
    capabilities.setdefault("confirmations", False)
    capabilities["attachment_modalities"] = tuple(capabilities.get("attachment_modalities", ()))
    payload["certified_capabilities"] = RuntimeCapabilitySet(**capabilities)
    for field_name in (
        "tcb_manifest_id",
        "tcb_manifest_version",
        "tcb_structure_digest",
        "tcb_live_digest",
    ):
        payload.setdefault(field_name, "")
    payload.setdefault("full_workspace_contract_revision", "")
    for field_name in (
        "execution_family",
        "harness_recipe_id",
        "harness_recipe_revision",
        "harness_recipe_digest",
        "provider_capability_catalog_digest",
        "semantic_projection_compiler_revision",
        "tool_contract_revision",
        "context_policy_revision",
    ):
        payload.setdefault(field_name, "")
    return CapabilityCertificate(**payload)


def _workspace_agentic_profile_binding(document: dict[str, Any]) -> WorkspaceAgenticProfileBinding:
    payload = dict(document)
    payload["actor_policy"] = _actor_selection_policy(payload["actor_policy"])
    payload["workspace_policy_ceiling"] = _agentic_runtime_policy(payload["workspace_policy_ceiling"])
    return WorkspaceAgenticProfileBinding(**payload)


def _agentic_runtime_policy(document: dict[str, Any]) -> AgenticRuntimePolicy:
    payload = dict(document)
    payload.setdefault("allow_filesystem_list", False)
    for field_name in ("allowed_surface_kinds", "allowed_tool_handles", "allowed_remote_data_classes"):
        payload[field_name] = tuple(payload.get(field_name, ()))
    return AgenticRuntimePolicy(**payload)


def _agentic_context_policy(
    document: dict[str, Any] | AgenticContextPolicy | None,
) -> AgenticContextPolicy | None:
    if document is None or isinstance(document, AgenticContextPolicy):
        return document
    return AgenticContextPolicy(**dict(document))


def _routing_constraint(document: dict[str, Any]) -> RoutingConstraint:
    payload = dict(document)
    for field_name in ("allowed_upstream_ids", "allowed_quantizations"):
        payload[field_name] = tuple(payload.get(field_name, ()))
    return RoutingConstraint(**payload)


def _actor_selection_policy(document: dict[str, Any]) -> ActorSelectionPolicy:
    payload = dict(document)
    for field_name in (
        "allowed_user_ids",
        "allowed_workspace_role_ids",
        "allowed_agent_type_ids",
    ):
        payload[field_name] = tuple(payload.get(field_name, ()))
    return ActorSelectionPolicy(**payload)


def _save_revisioned_record(
    collection: DocumentCollection,
    *,
    identity: dict[str, Any],
    payload: dict[str, Any],
    expected_revision: int | None,
    label: str,
) -> None:
    if expected_revision is None:
        _existing, inserted = collection.insert_one_if_absent(identity, payload)
        if not inserted:
            raise AgenticProfileConflictError(f"{label} already exists.")
        return
    if payload.get("revision") != expected_revision + 1:
        raise AgenticProfileConflictError(f"{label} revision must increment by exactly one.")
    updated = collection.compare_and_set(
        {**identity, "revision": expected_revision},
        {"$set": payload},
    )
    if not updated:
        raise AgenticProfileConflictError(f"{label} revision conflict.")
