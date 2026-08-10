"""Pure ordered application of typed domain operations."""

from __future__ import annotations

from typing import Any

from project_ir import IRValidationError, ProjectIR
from project_ir.canonical import canonical_copy, canonical_dumps
from project_ir.invariants import build_index

from .batches import OperationBatch
from .content_operations import apply_content_operation
from .errors import ProjectError
from .property_operations import apply_property_operation
from .timeline_operations import apply_timeline_operation


def apply_operation_batch(
    base_document: dict[str, Any],
    batch: OperationBatch,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    document = canonical_copy(base_document)
    _check_preconditions(document, batch)
    applied: list[str] = []
    for index, operation in enumerate(batch.operations):
        operation_path = f"/operations/{index}"
        try:
            handled = apply_timeline_operation(
                document,
                operation,
                batch_id=batch.operation_batch_id,
                operation_index=index,
            )
            handled = handled or apply_property_operation(document, operation)
            handled = handled or apply_content_operation(document, operation)
        except ProjectError as error:
            if not error.path:
                error.path = operation_path
            raise
        if not handled:
            raise ProjectError(
                "operation_type_unsupported",
                "Operation type is not supported by Project IR v1.",
                path=f"{operation_path}/type",
                details={"operation_type": operation.get("type")},
            )
        applied.append(str(operation["type"]))
    if canonical_dumps(document) == canonical_dumps(base_document):
        raise ProjectError("operation_batch_no_change", "Operation batch produced no project change.")
    try:
        validated = ProjectIR.parse(document, workspace_id=batch.workspace_id)
    except IRValidationError as error:
        raise ProjectError(
            "operation_result_invalid",
            "Operation batch produced invalid Project IR.",
            details={"issues": [item.to_dict() for item in error.issues]},
        ) from error
    return validated.to_dict(), tuple(applied)


def _check_preconditions(document: dict[str, Any], batch: OperationBatch) -> None:
    problems = []
    index = build_index(document, problems)
    known_ids = set(index.id_paths)
    for position, precondition in enumerate(batch.preconditions):
        kind = precondition.get("type")
        path = f"/preconditions/{position}"
        if kind == "head_is":
            if set(precondition) != {"type", "revision_id"}:
                raise ProjectError("precondition_shape_invalid", "head_is precondition is invalid.", path=path)
            if precondition.get("revision_id") != batch.base_revision_id:
                raise ProjectError(
                    "precondition_failed",
                    "Head precondition does not match batch base revision.",
                    path=path,
                    status_code=409,
                )
        elif kind in {"entity_exists", "entity_absent"}:
            if set(precondition) != {"type", "entity_id"}:
                raise ProjectError("precondition_shape_invalid", "Entity precondition is invalid.", path=path)
            exists = precondition.get("entity_id") in known_ids
            expected = kind == "entity_exists"
            if exists != expected:
                raise ProjectError(
                    "precondition_failed",
                    "Entity existence precondition failed.",
                    path=path,
                    details={"entity_id": precondition.get("entity_id")},
                    status_code=409,
                )
