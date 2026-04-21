"""Packaging helpers for SDK-created Maverick app source trees."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import tarfile

from core.app_sdk.models import AppSdkPackageResult
from core.app_sdk.service import validate_app_source
from core.app_sdk.errors import AppSdkValidationError
from core.apps.contracts import parse_app_contract_file


EXCLUDED_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "runtime",
    "tmp",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".duckdb", ".db"}


def package_app_source(app_root: str | Path, *, output_path: str | Path | None = None) -> AppSdkPackageResult:
    """Create a deterministic tar.gz package for one valid app source tree."""
    root = Path(app_root).resolve()
    validation = validate_app_source(root)
    if not validation.valid:
        details = "; ".join(issue.message for issue in validation.issues)
        raise AppSdkValidationError(f"Cannot package invalid app source `{root}`: {details}")
    parsed = parse_app_contract_file(root)
    artifact = Path(output_path).resolve() if output_path is not None else root.parent / f"{parsed.app_id}-{parsed.version}.tar.gz"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    files = _package_files(root)
    with tarfile.open(artifact, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=str(Path(root.name) / path.relative_to(root)), recursive=False)
    checksum = _sha256(artifact)
    manifest = {
        "app_id": parsed.app_id,
        "version": parsed.version,
        "contract_version": parsed.contract.compatibility.contract_version,
        "distribution": {
            "mode": parsed.contract.distribution.mode,
            "source_access": parsed.contract.distribution.source_access,
        },
        "artifact": artifact.name,
        "checksum_sha256": checksum,
        "files": [str(path.relative_to(root)) for path in files],
        "provenance": {
            "packager": "maverick-app-sdk",
            "source_root": str(root),
        },
    }
    manifest_path = artifact.with_suffix(artifact.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return AppSdkPackageResult(
        app_id=parsed.app_id,
        version=parsed.version,
        app_root=str(root),
        artifact_path=str(artifact),
        manifest_path=str(manifest_path),
        checksum_sha256=checksum,
        files_packaged=[str(path.relative_to(root)) for path in files],
    )


def _package_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(part in EXCLUDED_NAMES for part in path.relative_to(root).parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
