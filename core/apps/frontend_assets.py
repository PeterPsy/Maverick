"""Generated frontend asset manifests and immutable-cache verification."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit


FRONTEND_ASSET_MANIFEST_NAME = "maverick-frontend-assets.json"
FRONTEND_ASSET_MANIFEST_SCHEMA = "maverick.frontend-assets.v2"
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_BUILD_ID = re.compile(r"^[0-9a-f]{12,64}$")
_PRECACHE_URL = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@/-]*$")


class FrontendAssetManifestError(ValueError):
    """A generated asset manifest is unsafe or does not match its build."""


@dataclass(frozen=True, slots=True)
class FrontendAssetRecord:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FrontendPrecacheRecord:
    url: str
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FrontendAssetManifest:
    build_id: str
    entrypoints: tuple[str, ...]
    immutable: tuple[FrontendAssetRecord, ...]
    revalidated: tuple[FrontendAssetRecord, ...]
    precache: tuple[FrontendPrecacheRecord, ...] = ()
    navigation_fallback: str | None = None

    def immutable_record(self, path: str) -> FrontendAssetRecord | None:
        return next((record for record in self.immutable if record.path == path), None)

    def record(self, path: str) -> FrontendAssetRecord | None:
        return next((record for record in (*self.immutable, *self.revalidated) if record.path == path), None)


def load_frontend_asset_manifest(
    frontend_root: Path,
    *,
    required: bool = False,
    verify_files: bool = False,
) -> FrontendAssetManifest | None:
    """Load a normalized manifest and optionally verify every declared file."""

    root = frontend_root.resolve()
    manifest_path = root / FRONTEND_ASSET_MANIFEST_NAME
    if not manifest_path.is_file():
        if required:
            raise FrontendAssetManifestError(f"Missing {FRONTEND_ASSET_MANIFEST_NAME}.")
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FrontendAssetManifestError("Frontend asset manifest is not valid UTF-8 JSON.") from error
    manifest = _parse_manifest(payload)
    if verify_files:
        verify_frontend_asset_manifest(root, manifest)
    return manifest


def verify_frontend_asset_manifest(frontend_root: Path, manifest: FrontendAssetManifest) -> None:
    """Verify that all records exist beneath the build root with exact bytes."""

    root = frontend_root.resolve()
    for path in manifest.entrypoints:
        candidate = _resolved_asset_path(root, path)
        if not candidate.is_file():
            raise FrontendAssetManifestError(f"Missing frontend entrypoint `{path}`.")
    for record in (*manifest.immutable, *manifest.revalidated):
        candidate = _resolved_asset_path(root, record.path)
        if not candidate.is_file():
            raise FrontendAssetManifestError(f"Missing declared frontend asset `{record.path}`.")
        try:
            body = candidate.read_bytes()
        except OSError as error:
            raise FrontendAssetManifestError(f"Unable to read declared frontend asset `{record.path}`.") from error
        verify_frontend_asset_bytes(record, body)


def verify_frontend_asset_bytes(record: FrontendAssetRecord, body: bytes) -> None:
    """Verify one served representation against its generated manifest record."""

    if len(body) != record.size_bytes:
        raise FrontendAssetManifestError(f"Size mismatch for frontend asset `{record.path}`.")
    digest = hashlib.sha256(body).hexdigest()
    if digest != record.sha256:
        raise FrontendAssetManifestError(f"Digest mismatch for frontend asset `{record.path}`.")


def write_conservative_frontend_asset_manifest(frontend_root: Path) -> FrontendAssetManifest:
    """Generate a safe manifest for builds without a native bundler plugin.

    Every file is revalidated; only a build-aware plugin may assert that an
    output is content-addressed and therefore immutable.
    """

    root = frontend_root.resolve()
    records: list[FrontendAssetRecord] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file() or candidate.name == FRONTEND_ASSET_MANIFEST_NAME:
            continue
        relative = candidate.relative_to(root).as_posix()
        if candidate.suffix.lower() == ".map":
            continue
        body = candidate.read_bytes()
        records.append(FrontendAssetRecord(path=relative, sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body)))
    entrypoints = tuple(record.path for record in records if record.path.endswith(".html"))
    if not entrypoints:
        raise FrontendAssetManifestError("Frontend build does not contain an HTML entrypoint.")
    build_id = _records_build_id(entrypoints=entrypoints, immutable=(), revalidated=records)
    payload = _manifest_payload(build_id=build_id, entrypoints=entrypoints, immutable=(), revalidated=records)
    (root / FRONTEND_ASSET_MANIFEST_NAME).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return _parse_manifest(payload)


def _parse_manifest(payload: Any) -> FrontendAssetManifest:
    if not isinstance(payload, dict) or payload.get("schema") != FRONTEND_ASSET_MANIFEST_SCHEMA:
        raise FrontendAssetManifestError(f"Frontend asset manifest must use `{FRONTEND_ASSET_MANIFEST_SCHEMA}`.")
    build_id = str(payload.get("build_id") or "")
    if not _BUILD_ID.fullmatch(build_id):
        raise FrontendAssetManifestError("Frontend asset manifest build_id must be a lowercase hexadecimal digest.")
    entrypoints_payload = payload.get("entrypoints")
    if not isinstance(entrypoints_payload, list) or not entrypoints_payload:
        raise FrontendAssetManifestError("Frontend asset manifest requires entrypoints.")
    entrypoints = tuple(_safe_asset_path(value) for value in entrypoints_payload)
    immutable = _parse_records(payload.get("immutable"), field="immutable")
    revalidated = _parse_records(payload.get("revalidated"), field="revalidated")
    declared_paths = [record.path for record in (*immutable, *revalidated)]
    if len(declared_paths) != len(set(declared_paths)):
        raise FrontendAssetManifestError("Frontend asset paths must be unique across cache classes.")
    if any(entrypoint not in set(declared_paths) for entrypoint in entrypoints):
        raise FrontendAssetManifestError("Every frontend entrypoint must have a verified asset record.")
    precache = _parse_precache(payload.get("precache", []), records=(*immutable, *revalidated))
    if "offline" in payload:
        raise FrontendAssetManifestError("Frontend asset manifest must not declare superseded fallback metadata.")
    navigation_fallback = None
    if payload.get("navigation_fallback") is not None:
        navigation_fallback = _safe_asset_path(payload.get("navigation_fallback"))
        if navigation_fallback not in set(entrypoints):
            raise FrontendAssetManifestError("Navigation fallback must name a verified HTML entrypoint.")
        if not any(record.path == navigation_fallback for record in precache):
            raise FrontendAssetManifestError("Navigation fallback must be selected for precache.")
    return FrontendAssetManifest(
        build_id=build_id,
        entrypoints=entrypoints,
        immutable=immutable,
        revalidated=revalidated,
        precache=precache,
        navigation_fallback=navigation_fallback,
    )


def _parse_records(value: Any, *, field: str) -> tuple[FrontendAssetRecord, ...]:
    if not isinstance(value, list):
        raise FrontendAssetManifestError(f"Frontend asset manifest `{field}` must be an array.")
    records: list[FrontendAssetRecord] = []
    for raw_record in value:
        if not isinstance(raw_record, dict):
            raise FrontendAssetManifestError(f"Frontend asset manifest `{field}` records must be objects.")
        path = _safe_asset_path(raw_record.get("path"))
        digest = str(raw_record.get("sha256") or "")
        size_bytes = raw_record.get("size_bytes")
        if not _HEX_DIGEST.fullmatch(digest):
            raise FrontendAssetManifestError(f"Frontend asset `{path}` has an invalid SHA-256 digest.")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
            raise FrontendAssetManifestError(f"Frontend asset `{path}` has an invalid size.")
        records.append(FrontendAssetRecord(path=path, sha256=digest, size_bytes=size_bytes))
    return tuple(records)


def _parse_precache(
    value: Any,
    *,
    records: tuple[FrontendAssetRecord, ...],
) -> tuple[FrontendPrecacheRecord, ...]:
    if not isinstance(value, list):
        raise FrontendAssetManifestError("Frontend asset manifest `precache` must be an array.")
    records_by_path = {record.path: record for record in records}
    parsed: list[FrontendPrecacheRecord] = []
    for raw_record in value:
        if not isinstance(raw_record, dict):
            raise FrontendAssetManifestError("Frontend precache records must be objects.")
        url = str(raw_record.get("url") or "")
        parsed_url = urlsplit(url)
        decoded_path = unquote(parsed_url.path)
        decoded_segments = decoded_path.split("/")
        if (
            not url.startswith("/")
            or not _PRECACHE_URL.fullmatch(url)
            or url.startswith("//")
            or "//" in url
            or parsed_url.scheme
            or parsed_url.netloc
            or parsed_url.query
            or parsed_url.fragment
            or parsed_url.path != url
            or "%" in url
            or "\\" in decoded_path
            or "//" in decoded_path
            or any(part in {".", ".."} for part in decoded_segments)
            or decoded_path == "/sw.js"
            or decoded_path == "/api"
            or decoded_path.startswith("/api/")
            or decoded_path == "/ws"
            or decoded_path.startswith("/ws/")
            or any(part in {"backend", "sidecar"} for part in decoded_segments)
            or any(character in url for character in "\r\n\0")
        ):
            raise FrontendAssetManifestError(f"Unsafe frontend precache URL `{url}`.")
        path = _safe_asset_path(raw_record.get("path"))
        record = records_by_path.get(path)
        if record is None:
            raise FrontendAssetManifestError(f"Frontend precache path is not declared: `{path}`.")
        raw_size = raw_record.get("size_bytes")
        if (
            raw_record.get("sha256") != record.sha256
            or not isinstance(raw_size, int)
            or isinstance(raw_size, bool)
            or raw_size != record.size_bytes
        ):
            raise FrontendAssetManifestError(f"Frontend precache metadata does not match `{path}`.")
        parsed.append(
            FrontendPrecacheRecord(
                url=url,
                path=path,
                sha256=record.sha256,
                size_bytes=record.size_bytes,
            )
        )
    urls = [record.url for record in parsed]
    if len(urls) != len(set(urls)):
        raise FrontendAssetManifestError("Frontend precache URLs must be unique.")
    return tuple(parsed)


def _safe_asset_path(value: Any) -> str:
    text = str(value or "")
    pure = PurePosixPath(text)
    if (
        not text
        or text.startswith("/")
        or "\\" in text
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != text
        or text == FRONTEND_ASSET_MANIFEST_NAME
    ):
        raise FrontendAssetManifestError(f"Unsafe frontend asset path `{text}`.")
    return text


def _resolved_asset_path(root: Path, relative: str) -> Path:
    safe = _safe_asset_path(relative)
    candidate = (root / safe).resolve()
    if root not in candidate.parents:
        raise FrontendAssetManifestError(f"Frontend asset path escapes its build root: `{relative}`.")
    return candidate


def _records_build_id(
    *,
    entrypoints: Iterable[str],
    immutable: Iterable[FrontendAssetRecord],
    revalidated: Iterable[FrontendAssetRecord],
) -> str:
    payload = _manifest_payload(build_id="", entrypoints=entrypoints, immutable=immutable, revalidated=revalidated)
    payload.pop("build_id")
    return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()


def _manifest_payload(
    *,
    build_id: str,
    entrypoints: Iterable[str],
    immutable: Iterable[FrontendAssetRecord],
    revalidated: Iterable[FrontendAssetRecord],
) -> dict[str, Any]:
    return {
        "schema": FRONTEND_ASSET_MANIFEST_SCHEMA,
        "build_id": build_id,
        "entrypoints": list(entrypoints),
        "immutable": [record.__dict__ if hasattr(record, "__dict__") else {"path": record.path, "sha256": record.sha256, "size_bytes": record.size_bytes} for record in immutable],
        "revalidated": [record.__dict__ if hasattr(record, "__dict__") else {"path": record.path, "sha256": record.sha256, "size_bytes": record.size_bytes} for record in revalidated],
    }
