"""Exact-payload-bound classification views for trusted Core tool results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Literal

from core.runtime.tool_errors import RuntimeToolError


RuntimeToolClassificationPath = tuple[str | int, ...]
_FILESYSTEM_IDENTITY_FIELDS = (
    "resource_identity",
    "resource_revision",
    "resource_digest",
)
_FILESYSTEM_MUTATION_IDENTITY_FIELDS = (
    "previous_resource_revision",
    "previous_resource_digest",
    *_FILESYSTEM_IDENTITY_FIELDS,
    "instruction_scope_digest",
    "instruction_revisions",
)


@dataclass(frozen=True)
class RuntimeToolClassificationProjection:
    """Omit typed Core-owned metadata without changing the bound result bytes."""

    payload_digest: str
    omitted_paths: tuple[RuntimeToolClassificationPath, ...]
    projected_payload: bytes
    content_type: Literal["application/json", "text/plain"] = "application/json"

    def __post_init__(self) -> None:
        if (
            not _sha256(self.payload_digest)
            or not self.omitted_paths
            or not _valid_omitted_paths(self.omitted_paths)
            or self.content_type not in {"application/json", "text/plain"}
        ):
            raise RuntimeToolError("tool_result_classification_projection_invalid")
        try:
            projected = json.loads(self.projected_payload)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeToolError(
                "tool_result_classification_projection_invalid"
            ) from error
        if (
            not isinstance(projected, dict)
            or _canonical_tool_payload(projected) != self.projected_payload
        ):
            raise RuntimeToolError("tool_result_classification_projection_invalid")

    @classmethod
    def bind(
        cls,
        payload: dict[str, object],
        *,
        omitted_paths: tuple[RuntimeToolClassificationPath, ...],
        content_type: Literal[
            "application/json",
            "text/plain",
        ] = "application/json",
    ) -> RuntimeToolClassificationProjection:
        """Mint a typed projection only for paths present in these exact bytes."""
        projected = _tool_payload_without_paths(payload, omitted_paths)
        encoded_payload = _canonical_tool_payload(payload)
        return cls(
            payload_digest=hashlib.sha256(encoded_payload).hexdigest(),
            omitted_paths=omitted_paths,
            projected_payload=_canonical_tool_payload(projected),
            content_type=content_type,
        )

    def resolve(self, payload: dict[str, object]) -> dict[str, object]:
        """Return the projection only while its complete source payload matches."""
        digest = hashlib.sha256(_canonical_tool_payload(payload)).hexdigest()
        if not hmac.compare_digest(digest, self.payload_digest):
            raise RuntimeToolError("tool_result_classification_projection_invalid")
        projected = json.loads(self.projected_payload)
        expected = _tool_payload_without_paths(payload, self.omitted_paths)
        if (
            not isinstance(projected, dict)  # pragma: no cover - __post_init__
            or not hmac.compare_digest(
                _canonical_tool_payload(expected),
                self.projected_payload,
            )
        ):
            raise RuntimeToolError("tool_result_classification_projection_invalid")
        return projected

    def rebind_after_core_compaction(
        self,
        payload: dict[str, object],
        *,
        compaction_metadata_path: RuntimeToolClassificationPath | None = None,
    ) -> RuntimeToolClassificationProjection:
        """Retain typed omissions after trusted Core result compaction."""
        if compaction_metadata_path not in {
            None,
            ("output_compaction",),
            ("runtime_cli_output_compaction",),
        }:
            raise RuntimeToolError("tool_result_classification_projection_invalid")
        retained_paths = tuple(
            path for path in self.omitted_paths if _tool_payload_has_path(payload, path)
        )
        additional_paths = (
            (compaction_metadata_path,)
            if compaction_metadata_path is not None
            else ()
        )
        return type(self).bind(
            payload,
            omitted_paths=tuple(dict.fromkeys((*retained_paths, *additional_paths))),
            content_type=self.content_type,
        )


def filesystem_listing_classification_projection(
    payload: dict[str, object],
) -> RuntimeToolClassificationProjection:
    """Bind only Core-minted cursor/snapshot metadata for a listing result."""
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise RuntimeToolError("tool_result_classification_projection_invalid")
    nested_paths: list[RuntimeToolClassificationPath] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeToolError("tool_result_classification_projection_invalid")
        nested_paths.extend(
            (
                ("entries", index, "resource_identity"),
                ("entries", index, "resource_revision"),
            )
        )
    return RuntimeToolClassificationProjection.bind(
        payload,
        omitted_paths=(
            *_present_top_level_paths(
                payload,
                ("next_cursor", "snapshot_id", *_FILESYSTEM_IDENTITY_FIELDS),
            ),
            *nested_paths,
        ),
    )


def filesystem_read_classification_projection(
    payload: dict[str, object],
) -> RuntimeToolClassificationProjection:
    """Bind only Core-minted resource identity for a filesystem read."""
    return RuntimeToolClassificationProjection.bind(
        payload,
        omitted_paths=_present_top_level_paths(
            payload,
            _FILESYSTEM_IDENTITY_FIELDS,
        ),
    )


def filesystem_mutation_classification_projection(
    payload: dict[str, object],
) -> RuntimeToolClassificationProjection:
    """Bind only Core-minted resource/instruction identity after mutation."""
    return RuntimeToolClassificationProjection.bind(
        payload,
        omitted_paths=_present_top_level_paths(
            payload,
            _FILESYSTEM_MUTATION_IDENTITY_FIELDS,
        ),
    )


def _present_top_level_paths(
    payload: dict[str, object],
    field_names: tuple[str, ...],
) -> tuple[RuntimeToolClassificationPath, ...]:
    return tuple((field_name,) for field_name in field_names if field_name in payload)


def _canonical_tool_payload(payload: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RuntimeToolError(
            "tool_result_classification_projection_invalid"
        ) from error


def _tool_payload_without_paths(
    payload: dict[str, object],
    omitted_paths: tuple[RuntimeToolClassificationPath, ...],
) -> dict[str, object]:
    if not isinstance(payload, dict) or not omitted_paths:
        raise RuntimeToolError("tool_result_classification_projection_invalid")
    projected = deepcopy(payload)
    for path in omitted_paths:
        parent, field_name = _tool_payload_path_parent(projected, path)
        if not isinstance(parent, dict) or field_name not in parent:
            raise RuntimeToolError("tool_result_classification_projection_invalid")
        del parent[field_name]
    return projected


def _tool_payload_has_path(
    payload: dict[str, object],
    path: RuntimeToolClassificationPath,
) -> bool:
    try:
        parent, field_name = _tool_payload_path_parent(payload, path)
    except RuntimeToolError:
        return False
    return isinstance(parent, dict) and field_name in parent


def _tool_payload_path_parent(
    payload: dict[str, object],
    path: RuntimeToolClassificationPath,
) -> tuple[object, str]:
    if (
        not isinstance(path, tuple)
        or not path
        or not isinstance(path[-1], str)
        or not path[-1]
    ):
        raise RuntimeToolError("tool_result_classification_projection_invalid")
    current: object = payload
    for part in path[:-1]:
        if isinstance(part, str) and part:
            if not isinstance(current, dict) or part not in current:
                raise RuntimeToolError(
                    "tool_result_classification_projection_invalid"
                )
            current = current[part]
        elif isinstance(part, int) and not isinstance(part, bool) and part >= 0:
            if not isinstance(current, list) or part >= len(current):
                raise RuntimeToolError(
                    "tool_result_classification_projection_invalid"
                )
            current = current[part]
        else:
            raise RuntimeToolError("tool_result_classification_projection_invalid")
    return current, path[-1]


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_omitted_paths(
    paths: tuple[RuntimeToolClassificationPath, ...],
) -> bool:
    if not isinstance(paths, tuple):
        return False
    valid = all(
        isinstance(path, tuple)
        and bool(path)
        and all(
            (isinstance(part, str) and bool(part))
            or (isinstance(part, int) and not isinstance(part, bool) and part >= 0)
            for part in path
        )
        and isinstance(path[-1], str)
        for path in paths
    )
    return valid and len(set(paths)) == len(paths)


__all__ = [
    "RuntimeToolClassificationPath",
    "RuntimeToolClassificationProjection",
    "filesystem_listing_classification_projection",
    "filesystem_mutation_classification_projection",
    "filesystem_read_classification_projection",
]
