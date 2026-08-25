"""Re-sign verified static web content for one exact runtime compatibility binding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any

from opendesign_artifact import selected_asset, sha256_file, write_canonical_json
from opendesign_supply_chain import read_json
from opendesign_web_materialization import publish_web_overlay
from opendesign_web_overlay import VerifiedWebOverlay, verify_web_overlay, web_overlay_identity


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COPIED_CONTENT = (
    "static.tar.gz",
    "files.json",
    "sbom.cdx.json",
    "licenses.json",
    "NOTICE",
)


class WebRebindError(RuntimeError):
    """Raised when a compatibility-only web derivation cannot be proven safe."""


@dataclass(frozen=True)
class WebRebindResult:
    overlay: VerifiedWebOverlay
    source_web_overlay_sha256: str
    cache_hit: bool
    derivations: int
    reproducible: bool


def rebind_release_overlay(
    *,
    source_registry_root: Path,
    source_web_overlay_sha256: str,
    destination_registry_root: Path,
    bundle_manifest: dict[str, Any],
    service_root: Path,
    signing_key: Path,
    trust_contract: Path,
    work_parent: Path,
) -> WebRebindResult:
    """Create two identical signed derivations from one fully verified v2 overlay."""
    source_registry = _real_directory(source_registry_root, "source web registry")
    destination_registry = _real_directory(destination_registry_root, "destination web registry")
    work = _real_directory(work_parent, "web rebind work root")
    source = verify_web_overlay(
        source_registry / source_web_overlay_sha256,
        expected_digest=source_web_overlay_sha256,
        registry_root=source_registry,
        trust_contract=trust_contract,
    )
    source_manifest = read_json(source.path / "manifest.json")
    if source_manifest.get("schema_version") != "2":
        raise WebRebindError("web compatibility rebind requires a verified v2 source overlay")

    target_runtime = str(selected_asset(bundle_manifest, require_artifact_digest=True)["sha256"])
    if not SHA256_RE.fullmatch(target_runtime):
        raise WebRebindError("target runtime digest is invalid")
    if target_runtime in source.compatible_runtime_artifact_sha256:
        raise WebRebindError("web compatibility rebind must not be a no-op")
    _validate_source_binding(
        source_manifest,
        bundle_manifest=bundle_manifest,
        service_root=service_root,
    )

    with tempfile.TemporaryDirectory(prefix="od-web-rebind-", dir=work) as temporary:
        temporary_root = Path(temporary)
        try:
            derivations = []
            for sequence in (1, 2):
                derivation = temporary_root / f"derive-{sequence}"
                _derive_rebound_overlay(
                    derivation,
                    source=source,
                    source_manifest=source_manifest,
                    target_runtime_artifact_sha256=target_runtime,
                    signing_key=signing_key,
                )
                derivations.append(derivation)
            _assert_byte_reproducible(derivations[0], derivations[1])
            rebound_manifest = read_json(derivations[0] / "manifest.json")
            rebound_digest = rebound_manifest.get("web_overlay_sha256")
            if not isinstance(rebound_digest, str) or not SHA256_RE.fullmatch(rebound_digest):
                raise WebRebindError("rebound web overlay identity is invalid")
            overlay, cache_hit = publish_web_overlay(
                derivations[0],
                registry_root=destination_registry,
                expected_digest=rebound_digest,
                trust_contract=trust_contract,
            )
        finally:
            _make_discardable(temporary_root)
    if overlay.compatible_runtime_artifact_sha256 != frozenset({target_runtime}):
        raise WebRebindError("published web overlay has an ambiguous runtime compatibility set")
    return WebRebindResult(overlay, source_web_overlay_sha256, cache_hit, 2, True)


def _validate_source_binding(
    source_manifest: dict[str, Any],
    *,
    bundle_manifest: dict[str, Any],
    service_root: Path,
) -> None:
    compatibility = source_manifest.get("compatibility")
    expected = {
        "od_version": bundle_manifest["upstream"]["release_version"],
        "upstream_commit": bundle_manifest["upstream"]["commit"],
        "platform": bundle_manifest["distribution"]["platform"],
    }
    if not isinstance(compatibility, dict) or any(
        compatibility.get(key) != value for key, value in expected.items()
    ):
        raise WebRebindError("source web overlay does not match the selected upstream release")

    series = read_json(service_root / bundle_manifest["fallback_build"]["patch_series"])
    patch_digests = {
        str(entry.get("component")): str(entry.get("sha256"))
        for entry in series.get("patches", [])
        if isinstance(entry, dict) and entry.get("component") in {"web-build", "web-react"}
    }
    inputs = source_manifest.get("inputs")
    if not isinstance(inputs, dict) or {
        "web-build": inputs.get("web_build_patch_sha256"),
        "web-react": inputs.get("web_react_patch_sha256"),
    } != patch_digests:
        raise WebRebindError("source web overlay was not built from the selected web patches")


def _derive_rebound_overlay(
    root: Path,
    *,
    source: VerifiedWebOverlay,
    source_manifest: dict[str, Any],
    target_runtime_artifact_sha256: str,
    signing_key: Path,
) -> None:
    root.mkdir(mode=0o755)
    for relative in COPIED_CONTENT:
        shutil.copy2(source.path / relative, root / relative)
    shutil.copytree(source.static_dir, root / "static", copy_function=shutil.copy2)

    compatibility = {
        **source_manifest["compatibility"],
        "runtime_artifact_sha256": [target_runtime_artifact_sha256],
    }
    inputs = source_manifest["inputs"]
    descriptors = {
        name: _descriptor(root / relative, relative)
        for name, relative in {
            "static_archive": "static.tar.gz",
            "file_manifest": "files.json",
            "sbom": "sbom.cdx.json",
            "licenses": "licenses.json",
            "notice": "NOTICE",
        }.items()
    }
    digest = web_overlay_identity(
        static_archive_sha256=str(descriptors["static_archive"]["sha256"]),
        file_manifest_sha256=str(descriptors["file_manifest"]["sha256"]),
        sbom_sha256=str(descriptors["sbom"]["sha256"]),
        licenses_sha256=str(descriptors["licenses"]["sha256"]),
        notice_sha256=str(descriptors["notice"]["sha256"]),
        compatibility=compatibility,
        inputs=inputs,
    )
    provenance = read_json(source.path / "provenance.json")
    provenance = {
        **provenance,
        "subject": {"web_overlay_sha256": digest},
        "compatibility_rebind": {
            "method": "verified-static-content-v1",
            "source_web_overlay_sha256": source.web_overlay_sha256,
            "target_runtime_artifact_sha256": target_runtime_artifact_sha256,
        },
    }
    write_canonical_json(root / "provenance.json", provenance)
    manifest = {
        "schema_version": "2",
        "web_overlay_sha256": digest,
        **descriptors,
        "compatibility": compatibility,
        "inputs": inputs,
        "provenance": _descriptor(root / "provenance.json", "provenance.json"),
        "signature": {"algorithm": "Ed25519", "path": "manifest.sig"},
    }
    write_canonical_json(root / "manifest.json", manifest)
    _sign(root / "manifest.json", signing_key, root / "manifest.sig")


def _descriptor(path: Path, relative: str) -> dict[str, object]:
    return {"path": relative, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def _sign(document: Path, signing_key: Path, signature: Path) -> None:
    if signing_key.is_symlink() or not signing_key.is_file():
        raise WebRebindError("web overlay signing key must be a real file")
    completed = subprocess.run(
        [
            "openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(signing_key),
            "-in", str(document), "-out", str(signature),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise WebRebindError("web overlay compatibility signature failed")


def _assert_byte_reproducible(first: Path, second: Path) -> None:
    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    if first_files != second_files:
        raise WebRebindError("web compatibility derivations produced different file sets")
    for relative in first_files:
        if (first / relative).read_bytes() != (second / relative).read_bytes():
            raise WebRebindError(f"web compatibility derivations differ: {relative.as_posix()}")


def _real_directory(path: Path, label: str) -> Path:
    path = Path(path)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise WebRebindError(f"{label} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise WebRebindError(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _make_discardable(root: Path) -> None:
    if not root.exists() or root.is_symlink():
        return
    for path in root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
    root.chmod(0o755)
