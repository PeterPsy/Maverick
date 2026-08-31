"""Session-scoped filesystem post-image classification lineage.

Confined filesystem objects are intentionally short lived in the hosted loop.
Successful mutation results therefore provide the durable, Core-owned bridge
between the classified pre-image and an exact post-image observed by a later
orchestrator instance.
"""

from __future__ import annotations

import hashlib
import hmac

from core.egress.classification import (
    CanonicalSourceClassification,
    fail_closed_classification,
    join_classifications,
    validated_classification,
)
from core.runtime.confined_filesystem import FilesystemResourceObservation
from core.runtime.tool_private_payloads import (
    canonical_tool_arguments,
    decode_tool_arguments,
)


_POST_IMAGE_PATH_FIELDS = {
    "core-capability:filesystem.write": "path",
    "core-capability:filesystem.edit": "path",
    "core-capability:filesystem.patch": "path",
    "core-capability:filesystem.move": "destination_path",
}


def resolve_filesystem_mutation_lineage(
    *,
    observation: FilesystemResourceObservation,
    provenance: str,
    authoritative: CanonicalSourceClassification,
    ledger,
    session_id: str,
) -> CanonicalSourceClassification:
    """Join exact authoritative data with successful same-session mutations.

    Tool result payloads are held in authenticated private storage.  A lineage
    record is accepted only when its server-owned handle and persisted payload
    both identify the exact resource observation being classified.  Missing or
    unreadable mutation evidence fails closed rather than guessing whether it
    described the current post-image.
    """
    fallback = _fallback(observation, provenance)
    normalized_authority = _normalize_authority(
        observation,
        provenance,
        authoritative,
    )
    if normalized_authority is None or not str(session_id or "").strip():
        return fallback

    try:
        records = ledger.store.list_tool_invocations(session_id=session_id)
    except Exception:
        return fallback

    lineage: list[CanonicalSourceClassification] = []
    matched_incomplete = False
    for record in records:
        path_field = _POST_IMAGE_PATH_FIELDS.get(
            getattr(record, "resolved_tool_handle", None)
        )
        if (
            path_field is None
            or getattr(record, "state", None) != "succeeded"
            or getattr(record, "workspace_id", None) != observation.workspace_id
            or getattr(record, "session_id", None) != session_id
        ):
            continue
        if getattr(record, "result_provenance", None) != "tool_result":
            return fallback
        try:
            result = ledger.load_result(record)
        except Exception:
            return fallback
        if not _persisted_result_matches(record, result):
            return fallback
        if (
            not _well_formed_post_image(result, path_field)
            and getattr(record, "result_artifact_private_ref", None)
        ):
            try:
                artifact = ledger.load_result_artifact(record)
                if not _persisted_artifact_matches(record, artifact):
                    return fallback
                result = decode_tool_arguments(artifact)
            except Exception:
                return fallback
        if not _well_formed_post_image(result, path_field):
            return fallback
        if not _matches_observation(
            result,
            path_field=path_field,
            observation=observation,
        ):
            continue
        classification_revision = getattr(
            record,
            "result_classification_revision",
            None,
        )
        if classification_revision is not None and (
            not isinstance(classification_revision, int)
            or isinstance(classification_revision, bool)
            or classification_revision < 1
        ):
            return fallback
        rebound = validated_classification(
            data_class=getattr(record, "result_data_class", ""),
            provenance=provenance,
            trust_level=getattr(record, "result_trust_level", ""),
            source_ref=observation.resource_ref,
            source_revision=observation.resource_revision,
            source_digest=observation.resource_digest,
            resource_identity=observation.resource_identity,
            classification_revision=classification_revision,
        )
        if rebound.classification_revision is None:
            if classification_revision is not None:
                return fallback
            matched_incomplete = True
        else:
            lineage.append(rebound)

    sources: list[CanonicalSourceClassification] = []
    if normalized_authority.classification_revision is not None:
        sources.append(normalized_authority)
    sources.extend(lineage)
    if not sources:
        return fallback if matched_incomplete else normalized_authority

    joined = join_classifications(sources)
    revisions = tuple(source.classification_revision for source in joined.sources)
    return validated_classification(
        data_class=joined.effective_data_class,
        provenance=provenance,
        trust_level=joined.effective_trust_level,
        source_ref=observation.resource_ref,
        source_revision=observation.resource_revision,
        source_digest=observation.resource_digest,
        resource_identity=observation.resource_identity,
        classification_revision=(
            max(revisions) if all(item is not None for item in revisions) else None
        ),
    )


def _normalize_authority(
    observation: FilesystemResourceObservation,
    provenance: str,
    authoritative: CanonicalSourceClassification,
) -> CanonicalSourceClassification | None:
    normalized = join_classifications((authoritative,)).sources[0]
    if (
        normalized.provenance != provenance
        or normalized.source_ref != observation.resource_ref
        or normalized.source_revision != observation.resource_revision
        or normalized.source_digest != observation.resource_digest
        or normalized.resource_identity != observation.resource_identity
    ):
        return None
    return normalized


def _well_formed_post_image(result: object, path_field: str) -> bool:
    if not isinstance(result, dict):
        return False
    required = (
        path_field,
        "resource_identity",
        "resource_revision",
        "resource_digest",
    )
    return all(
        isinstance(result.get(field), str) and bool(str(result[field]).strip())
        for field in required
    )


def _persisted_result_matches(record, result: object) -> bool:
    if not isinstance(result, dict):
        return False
    try:
        digest = hashlib.sha256(canonical_tool_arguments(result)).hexdigest()
    except Exception:
        return False
    source_revision = str(getattr(record, "result_source_revision", "") or "")
    source_digest = str(getattr(record, "result_source_digest", "") or "")
    return hmac.compare_digest(digest, source_revision.lower()) and hmac.compare_digest(
        digest,
        source_digest.lower(),
    )


def _persisted_artifact_matches(record, artifact: object) -> bool:
    if not isinstance(artifact, bytes):
        return False
    expected_digest = str(
        getattr(record, "result_artifact_sha256", "") or ""
    ).lower()
    expected_size = getattr(record, "result_artifact_size_bytes", None)
    return (
        isinstance(expected_size, int)
        and not isinstance(expected_size, bool)
        and expected_size == len(artifact)
        and hmac.compare_digest(hashlib.sha256(artifact).hexdigest(), expected_digest)
    )


def _matches_observation(
    result: dict[str, object],
    *,
    path_field: str,
    observation: FilesystemResourceObservation,
) -> bool:
    return (
        result[path_field] == observation.resource_ref
        and result["resource_identity"] == observation.resource_identity
        and result["resource_revision"] == observation.resource_revision
        and str(result["resource_digest"]).lower()
        == observation.resource_digest.lower()
    )


def _fallback(
    observation: FilesystemResourceObservation,
    provenance: str,
) -> CanonicalSourceClassification:
    return fail_closed_classification(
        provenance=provenance,
        source_ref=observation.resource_ref,
        source_revision=observation.resource_revision,
        source_digest=observation.resource_digest,
        resource_identity=observation.resource_identity,
    )


__all__ = ["resolve_filesystem_mutation_lineage"]
