"""Bounded ZIP validation and immutable, content-addressed publication artifacts."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

from .errors import AppError
from .files import atomic_write, encoded, read_regular, sync_directory
from .policy import MAX_FILE, MAX_FILES, MAX_RATIO, MAX_TOTAL, MAX_ZIP, artifact_path, digest


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unpack(data: bytes, destination: Path, entrypoint: str):
    if not data or len(data) > MAX_ZIP:
        raise AppError("artifact_too_large")
    entrypoint, content_type = artifact_path(entrypoint)
    if not content_type.startswith("text/html"):
        raise AppError("invalid_entrypoint")
    inventory = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_FILES:
            raise AppError("artifact_too_large")
        for info in entries:
            name, mime = artifact_path(info.filename)
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if info.is_dir() or kind not in (0, stat.S_IFREG) or info.flag_bits & 1:
                raise AppError("invalid_artifact")
            if name in inventory or any(name.startswith(p + "/") or p.startswith(name + "/") for p in inventory):
                raise AppError("duplicate_artifact_path")
            if info.file_size > MAX_FILE or info.file_size > max(1, info.compress_size) * MAX_RATIO:
                raise AppError("artifact_too_large")
            with archive.open(info) as member:
                content = member.read(MAX_FILE + 1)
            total += len(content)
            if len(content) != info.file_size or len(content) > MAX_FILE or total > MAX_TOTAL:
                raise AppError("artifact_too_large")
            target = destination / name
            atomic_write(target, content)
            inventory[name] = {"sha256": sha(content), "size": len(content), "mime": mime}
    if entrypoint not in inventory:
        raise AppError("missing_entrypoint")
    return {"version": 1, "entrypoint": entrypoint, "files": inventory, "size_bytes": total}


def promote(root: Path, data: bytes, *, entrypoint="index.html"):
    artifact_digest = sha(data)
    tmp = root / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="bundle-", dir=tmp))
    try:
        manifest = unpack(data, staging / "files", entrypoint)
        manifest_data = encoded(manifest)
        atomic_write(staging / "manifest.json", manifest_data)
        atomic_write(staging / "bundle.zip", data)
        target = root / "public/artifacts" / artifact_digest
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            verify(root / "public", artifact_digest, sha(manifest_data))
        else:
            for directory, _, _ in os.walk(staging, topdown=False):
                sync_directory(Path(directory))
            os.rename(staging, target)
            sync_directory(target.parent)
        return {"digest": artifact_digest, "manifest_digest": sha(manifest_data),
                "size_bytes": len(data), "expanded_bytes": manifest["size_bytes"],
                "file_count": len(manifest["files"]), "entrypoint": entrypoint}
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as error:
        raise AppError("invalid_artifact") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def load_manifest(public_root, artifact_digest, manifest_digest):
    directory = public_root / "artifacts" / digest(artifact_digest)
    content = read_regular(directory / "manifest.json", 256 * 1024)
    if sha(content) != digest(manifest_digest):
        raise AppError("corrupt_artifact", 503)
    try:
        manifest = json.loads(content)
        if manifest.get("version") != 1 or not 0 < len(manifest["files"]) <= MAX_FILES:
            raise AppError("corrupt_artifact", 503)
        if manifest["entrypoint"] not in manifest["files"]:
            raise AppError("corrupt_artifact", 503)
        for name, item in manifest["files"].items():
            _, mime = artifact_path(name)
            digest(item["sha256"])
            if item["mime"] != mime or type(item["size"]) is not int or not 0 <= item["size"] <= MAX_FILE:
                raise AppError("corrupt_artifact", 503)
        return manifest
    except (KeyError, ValueError, TypeError) as error:
        raise AppError("corrupt_artifact", 503) from error


def verify(public_root, artifact_digest, manifest_digest):
    manifest = load_manifest(public_root, artifact_digest, manifest_digest)
    directory = public_root / "artifacts" / artifact_digest
    if sha(read_regular(directory / "bundle.zip", MAX_ZIP)) != artifact_digest:
        raise AppError("corrupt_artifact", 503)
    for name, item in manifest["files"].items():
        content = read_regular(directory / "files" / name, MAX_FILE)
        if len(content) != item["size"] or sha(content) != item["sha256"]:
            raise AppError("corrupt_artifact", 503)
    return manifest
