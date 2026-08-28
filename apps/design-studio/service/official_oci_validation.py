"""Strict validation primitives for official OpenDesign OCI release locks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


OFFICIAL_REGISTRY = "ghcr.io"
OFFICIAL_REPOSITORY = "nexu-io/od"
OFFICIAL_REDIRECT_HOSTS = ["ghcr.io", "pkg-containers.githubusercontent.com"]
OFFICIAL_PLATFORM = {"os": "linux", "architecture": "amd64"}


class OfficialOciValidationError(RuntimeError):
    """An official OCI descriptor is incomplete, unsafe, or inconsistent."""


def reject_duplicate_pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON object fields instead of silently taking the last."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def validate_oci_distribution(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate a digest-locked release from the sole official OCI origin."""
    upstream = _mapping(manifest, "upstream")
    distribution = _mapping(manifest, "distribution")
    expected_fields = {
        "primary",
        "registry",
        "repository",
        "reference",
        "platform",
        "index",
        "manifest",
        "config",
        "layers",
        "attestation",
        "expected_revision",
        "expected_version",
        "allowed_redirect_hosts",
        "max_blob_size_bytes",
        "minimum_mem_available_bytes",
    }
    if set(distribution) != expected_fields or distribution.get("primary") != "oci_import":
        raise OfficialOciValidationError("OpenDesign OCI distribution fields are unsupported")
    version = _required_string(upstream, "release_version")
    commit = _required_string(upstream, "commit")
    if distribution.get("registry") != OFFICIAL_REGISTRY or distribution.get("repository") != OFFICIAL_REPOSITORY:
        raise OfficialOciValidationError("OpenDesign OCI registry identity is not official")
    if distribution.get("reference") != version:
        raise OfficialOciValidationError("OpenDesign OCI reference does not match the selected version")
    if distribution.get("platform") != OFFICIAL_PLATFORM:
        raise OfficialOciValidationError("OpenDesign OCI platform is not authorized")
    if distribution.get("expected_revision") != commit:
        raise OfficialOciValidationError("OpenDesign OCI revision does not match upstream")
    if distribution.get("expected_version") != version:
        raise OfficialOciValidationError("OpenDesign OCI version does not match upstream")
    if distribution.get("allowed_redirect_hosts") != OFFICIAL_REDIRECT_HOSTS:
        raise OfficialOciValidationError("OpenDesign OCI redirect policy changed")
    max_blob_size = distribution.get("max_blob_size_bytes")
    minimum_memory = distribution.get("minimum_mem_available_bytes")
    if not _positive_integer(max_blob_size) or max_blob_size > 128 * 1024 * 1024:
        raise OfficialOciValidationError("OpenDesign OCI blob limit is invalid")
    if not _positive_integer(minimum_memory) or minimum_memory < 3 * 1024 * 1024 * 1024:
        raise OfficialOciValidationError("OpenDesign OCI memory floor is invalid")

    _descriptor(
        _mapping(distribution, "index"),
        media_type="application/vnd.oci.image.index.v1+json",
        label="index",
    )
    manifest_descriptor = _descriptor(
        _mapping(distribution, "manifest"),
        media_type="application/vnd.oci.image.manifest.v1+json",
        label="manifest",
    )
    _descriptor(
        _mapping(distribution, "config"),
        media_type="application/vnd.oci.image.config.v1+json",
        label="config",
    )
    layers = distribution.get("layers")
    if not isinstance(layers, list) or not layers:
        raise OfficialOciValidationError("OpenDesign OCI layers must be a non-empty list")
    layer_digests: set[str] = set()
    for layer in layers:
        if not isinstance(layer, dict):
            raise OfficialOciValidationError("OpenDesign OCI layer descriptor must be an object")
        descriptor = _descriptor(
            layer,
            media_type="application/vnd.oci.image.layer.v1.tar+gzip",
            label="layer",
        )
        if descriptor["size_bytes"] > max_blob_size:
            raise OfficialOciValidationError("OpenDesign OCI layer exceeds its pinned size limit")
        if descriptor["digest"] in layer_digests:
            raise OfficialOciValidationError("OpenDesign OCI layer digest is duplicated")
        layer_digests.add(descriptor["digest"])

    attestation = _mapping(distribution, "attestation")
    if set(attestation) != {"manifest", "config", "statement", "subject_manifest_digest"}:
        raise OfficialOciValidationError("OpenDesign OCI attestation fields are unsupported")
    _descriptor(
        _mapping(attestation, "manifest"),
        media_type="application/vnd.oci.image.manifest.v1+json",
        label="attestation manifest",
    )
    _descriptor(
        _mapping(attestation, "config"),
        media_type="application/vnd.oci.image.config.v1+json",
        label="attestation config",
    )
    statement = _mapping(attestation, "statement")
    if set(statement) != {"media_type", "predicate_type", "digest", "size_bytes"}:
        raise OfficialOciValidationError("OpenDesign OCI attestation statement descriptor is invalid")
    _descriptor(
        {key: statement[key] for key in ("media_type", "digest", "size_bytes")},
        media_type="application/vnd.in-toto+json",
        label="attestation statement",
    )
    if statement.get("predicate_type") != "https://slsa.dev/provenance/v1":
        raise OfficialOciValidationError("OpenDesign OCI attestation predicate type changed")
    if attestation.get("subject_manifest_digest") != manifest_descriptor["digest"]:
        raise OfficialOciValidationError("OpenDesign OCI attestation subject pin changed")
    return distribution


def _descriptor(descriptor: dict[str, Any], *, media_type: str, label: str) -> dict[str, Any]:
    if set(descriptor) != {"media_type", "digest", "size_bytes"}:
        raise OfficialOciValidationError(f"OpenDesign OCI {label} descriptor fields are invalid")
    if descriptor.get("media_type") != media_type:
        raise OfficialOciValidationError(f"OpenDesign OCI {label} media type changed")
    digest = descriptor.get("digest")
    if not isinstance(digest, str) or not _sha256_digest(digest):
        raise OfficialOciValidationError(f"OpenDesign OCI {label} digest is invalid")
    if not _positive_integer(descriptor.get("size_bytes")):
        raise OfficialOciValidationError(f"OpenDesign OCI {label} size is invalid")
    return descriptor


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise OfficialOciValidationError(f"OpenDesign OCI field {key} must be an object")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise OfficialOciValidationError(f"OpenDesign OCI field {key} must be a non-empty string")
    return value


def _sha256_digest(value: str) -> bool:
    body = value.removeprefix("sha256:")
    return value.startswith("sha256:") and len(body) == 64 and all(character in "0123456789abcdef" for character in body)


def _positive_integer(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


__all__ = [
    "OFFICIAL_PLATFORM",
    "OFFICIAL_REDIRECT_HOSTS",
    "OFFICIAL_REGISTRY",
    "OFFICIAL_REPOSITORY",
    "OfficialOciValidationError",
    "reject_duplicate_pairs",
    "validate_oci_distribution",
]
