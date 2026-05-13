"""Rendered document preview helpers for Storage."""

from __future__ import annotations

from base64 import b64encode
from contextlib import contextmanager
import fcntl
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile

from errors import StorageValidationError
from store import file_record


RENDERABLE_PREVIEW_KINDS = {"document", "presentation", "spreadsheet"}
MAX_RENDER_SOURCE_BYTES = 100 * 1024 * 1024
RENDER_TIMEOUT_SECONDS = 60
MAX_RENDER_CACHE_FILES = 120
MAX_RENDER_CACHE_BYTES = 300 * 1024 * 1024


def _preview_cache_root(data_root: Path) -> Path:
    return data_root / "rendered_previews"


@contextmanager
def _cache_lock(cache_path: Path):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = cache_path.with_suffix(cache_path.suffix + ".lock")
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _preview_cache_key(path: Path, record: dict) -> str:
    payload = "|".join(
        [
            str(path.resolve()),
            record["modified_at"],
            str(record["size_bytes"]),
            record["preview_kind"],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _libreoffice_binary() -> str:
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:
        raise StorageValidationError("Rendered preview requires LibreOffice, but it is not available.")
    return binary


def _convert_to_pdf(source: Path, target: Path) -> None:
    _convert_with_libreoffice(source, target, output_extension="pdf")


def _convert_to_png(source: Path, target: Path) -> None:
    _convert_with_libreoffice(source, target, output_extension="png")


def _convert_with_libreoffice(source: Path, target: Path, *, output_extension: str) -> None:
    binary = _libreoffice_binary()
    with tempfile.TemporaryDirectory(prefix="storage-render-") as temp_dir:
        temp_root = Path(temp_dir)
        out_dir = temp_root / "out"
        home_dir = temp_root / "home"
        out_dir.mkdir()
        home_dir.mkdir()
        command = [
            binary,
            "--headless",
            "--convert-to",
            output_extension,
            "--outdir",
            str(out_dir),
            str(source),
        ]
        result = subprocess.run(
            command,
            cwd=temp_root,
            env={"HOME": str(home_dir), "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT_SECONDS,
            check=False,
        )
        converted = out_dir / f"{source.stem}.{output_extension}"
        if result.returncode != 0 or not converted.is_file():
            detail = (result.stderr or result.stdout or f"LibreOffice did not produce a {output_extension.upper()} preview.").strip()
            raise StorageValidationError(f"Rendered preview failed: {detail}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(converted, target)


def _ensure_cached_conversion(source: Path, cache_path: Path, *, output_extension: str) -> bool:
    cache_hit = cache_path.is_file()
    if cache_hit:
        return True
    with _cache_lock(cache_path):
        if cache_path.is_file():
            return True
        if output_extension == "pdf":
            _convert_to_pdf(source, cache_path)
        else:
            _convert_to_png(source, cache_path)
        _evict_render_cache(cache_path.parent)
        return False


def _evict_render_cache(cache_root: Path) -> None:
    files = [path for path in cache_root.glob("*") if path.is_file() and path.suffix in {".pdf", ".png"}]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    total = 0
    for index, path in enumerate(files):
        size = path.stat().st_size
        total += size
        if index < MAX_RENDER_CACHE_FILES and total <= MAX_RENDER_CACHE_BYTES:
            continue
        path.unlink(missing_ok=True)


def rendered_preview_payload(*, path: Path, root: Path, role: str, data_root: Path) -> dict:
    """Return a PDF preview for a PDF or Office-style document."""
    record = file_record(role=role, root=root, path=path.resolve())
    if record["size_bytes"] > MAX_RENDER_SOURCE_BYTES:
        raise StorageValidationError("File is too large to render in Storage.")
    if record["preview_kind"] == "pdf":
        return {
            "file": record,
            "content_base64": b64encode(path.read_bytes()).decode("ascii"),
            "content_type": "application/pdf",
            "preview_kind": "pdf",
            "renderer": "native",
            "cache_hit": False,
        }
    if record["preview_kind"] not in RENDERABLE_PREVIEW_KINDS:
        raise StorageValidationError("Rendered preview is only available for PDF, DOCX, PPTX, and XLSX-style files.")

    cache_path = _preview_cache_root(data_root) / f"{_preview_cache_key(path, record)}.pdf"
    cache_hit = _ensure_cached_conversion(path, cache_path, output_extension="pdf")
    return {
        "file": record,
        "content_base64": b64encode(cache_path.read_bytes()).decode("ascii"),
        "content_type": "application/pdf",
        "preview_kind": "pdf",
        "renderer": "libreoffice",
        "cache_hit": cache_hit,
    }


def rendered_thumbnail_payload(*, path: Path, root: Path, role: str, data_root: Path) -> dict:
    """Return a static image thumbnail for card previews."""
    record = file_record(role=role, root=root, path=path.resolve())
    if record["size_bytes"] > MAX_RENDER_SOURCE_BYTES:
        raise StorageValidationError("File is too large to render in Storage.")
    if record["preview_kind"] not in RENDERABLE_PREVIEW_KINDS:
        raise StorageValidationError("Rendered thumbnails are only available for DOCX, PPTX, and XLSX-style files.")
    cache_path = _preview_cache_root(data_root) / f"{_preview_cache_key(path, record)}.png"
    cache_hit = _ensure_cached_conversion(path, cache_path, output_extension="png")
    return {
        "file": record,
        "content_base64": b64encode(cache_path.read_bytes()).decode("ascii"),
        "content_type": "image/png",
        "preview_kind": "image",
        "renderer": "libreoffice",
        "cache_hit": cache_hit,
    }
