"""Strict typed operation-batch envelope."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from project_ir.canonical import CanonicalizationError, canonical_copy, canonical_dumps, content_digest
from project_ir.security import security_issues

from .errors import ProjectError


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
BATCH_FIELDS = {
    "workspace_id",
    "project_id",
    "base_revision_id",
    "operation_batch_id",
    "preconditions",
    "actor",
    "operations",
    "autosave",
    "metadata",
}
ACTOR_KINDS = {"user", "agent", "system"}
PRECONDITION_TYPES = {"head_is", "entity_exists", "entity_absent"}


@dataclass(frozen=True)
class OperationBatch:
    workspace_id: str
    project_id: str
    base_revision_id: str
    operation_batch_id: str
    preconditions: tuple[dict[str, Any], ...]
    actor: dict[str, str]
    operations: tuple[dict[str, Any], ...]
    autosave: dict[str, Any]
    metadata: dict[str, Any]
    request: dict[str, Any]
    request_digest: str

    @classmethod
    def parse(cls, payload: object, *, trusted_workspace_id: str) -> "OperationBatch":
        if not isinstance(payload, dict):
            raise ProjectError("operation_batch_invalid", "Operation batch must be an object.")
        unknown = sorted(set(payload) - BATCH_FIELDS)
        missing = sorted(BATCH_FIELDS - set(payload))
        if unknown or missing:
            raise ProjectError(
                "operation_batch_shape_invalid",
                "Operation batch fields do not match the domain contract.",
                details={"missing": missing, "unknown": unknown},
            )
        try:
            canonical = canonical_dumps(payload)
        except CanonicalizationError as error:
            raise ProjectError("operation_batch_json_invalid", "Operation batch is not canonical JSON.") from error
        if len(canonical.encode("utf-8")) > 2_000_000:
            raise ProjectError("operation_batch_limit_exceeded", "Operation batch exceeds the byte limit.")
        forbidden = security_issues(payload)
        if forbidden:
            raise ProjectError(
                "operation_batch_forbidden_content",
                "Operation batch contains forbidden active or external content.",
                details={"issues": [item.to_dict() for item in forbidden]},
            )
        workspace_id = _identifier(payload.get("workspace_id"), "/workspace_id")
        if workspace_id != trusted_workspace_id:
            raise ProjectError(
                "workspace_mismatch",
                "Operation batch workspace does not match trusted context.",
                path="/workspace_id",
                status_code=403,
            )
        project_id = _identifier(payload.get("project_id"), "/project_id")
        base_revision_id = _identifier(payload.get("base_revision_id"), "/base_revision_id")
        batch_id = _identifier(payload.get("operation_batch_id"), "/operation_batch_id")
        actor = payload.get("actor")
        if not isinstance(actor, dict) or set(actor) != {"kind", "id"}:
            raise ProjectError("actor_invalid", "Actor must contain kind and id.", path="/actor")
        if actor.get("kind") not in ACTOR_KINDS:
            raise ProjectError("actor_kind_invalid", "Actor kind is unsupported.", path="/actor/kind")
        actor_id = _identifier(actor.get("id"), "/actor/id")
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations or len(operations) > 1000:
            raise ProjectError(
                "operations_invalid",
                "Operation batch requires between 1 and 1000 ordered operations.",
                path="/operations",
            )
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict) or not isinstance(operation.get("type"), str):
                raise ProjectError(
                    "operation_invalid",
                    "Every operation must be a typed object.",
                    path=f"/operations/{index}",
                )
        preconditions = payload.get("preconditions")
        if not isinstance(preconditions, list) or len(preconditions) > 256:
            raise ProjectError("preconditions_invalid", "Preconditions must be a bounded array.", path="/preconditions")
        for index, precondition in enumerate(preconditions):
            if not isinstance(precondition, dict) or precondition.get("type") not in PRECONDITION_TYPES:
                raise ProjectError(
                    "precondition_invalid",
                    "Precondition type is unsupported.",
                    path=f"/preconditions/{index}",
                )
        autosave = payload.get("autosave")
        if not isinstance(autosave, dict) or set(autosave) != {"enabled", "reason"}:
            raise ProjectError("autosave_invalid", "Autosave must contain enabled and reason.", path="/autosave")
        if not isinstance(autosave.get("enabled"), bool) or not isinstance(autosave.get("reason"), str):
            raise ProjectError("autosave_invalid", "Autosave values are invalid.", path="/autosave")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict) or len(metadata) > 128:
            raise ProjectError("batch_metadata_invalid", "Batch metadata must be a bounded object.", path="/metadata")
        request = canonical_copy(payload)
        return cls(
            workspace_id=workspace_id,
            project_id=project_id,
            base_revision_id=base_revision_id,
            operation_batch_id=batch_id,
            preconditions=tuple(canonical_copy(preconditions)),
            actor={"kind": str(actor["kind"]), "id": actor_id},
            operations=tuple(canonical_copy(operations)),
            autosave=canonical_copy(autosave),
            metadata=canonical_copy(metadata),
            request=request,
            request_digest=content_digest(request),
        )


def _identifier(value: object, path: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ProjectError("identifier_invalid", "Identifier is missing or malformed.", path=path)
    return value
