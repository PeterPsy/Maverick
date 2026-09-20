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
from time import monotonic, sleep
from urllib.parse import urlencode
from uuid import uuid4

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


@contextmanager
def _conversion_slot(cache_root: Path):
    """Bound expensive conversion processes across all Storage frames and workers."""
    deadline = monotonic() + RENDER_TIMEOUT_SECONDS
    while True:
        for index in range(2):
            handle = (cache_root / f'.converter-{index}.lock').open('a+')
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                continue
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
            return
        if monotonic() >= deadline:
            raise StorageValidationError('Preview conversion is busy; retry shortly.')
        sleep(.05)


def _preview_cache_key(path: Path, record: dict) -> str:
    stat = path.stat()
    payload = "|".join(
        [
            str(path.resolve()),
            record["modified_at"],
            str(record["size_bytes"]),
            record["preview_kind"],
            str((stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)),
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
        temporary = cache_path.with_name(f'.{cache_path.stem}-{uuid4().hex}.{output_extension}')
        before = source.stat()
        signature = lambda value: (value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_dev, value.st_ino)
        try:
            with _conversion_slot(cache_path.parent):
                if output_extension == "pdf":
                    _convert_to_pdf(source, temporary)
                else:
                    _convert_to_png(source, temporary)
            if signature(source.stat()) != signature(before):
                raise StorageValidationError("File changed during conversion; retry the preview.")
            temporary.replace(cache_path)
        finally:
            temporary.unlink(missing_ok=True)
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


def rendered_preview_path(*, path: Path, root: Path, role: str, data_root: Path, thumbnail: bool = False) -> tuple[Path, dict]:
    """Prepare the local derivative without loading it into a JSON response."""
    record = file_record(role=role, root=root, path=path.resolve())
    if record['size_bytes'] > MAX_RENDER_SOURCE_BYTES:
        raise StorageValidationError('File is too large to render in Storage.')
    if record['preview_kind'] == 'pdf' and not thumbnail:
        return path, {'file': record, 'content_type': 'application/pdf', 'preview_kind': 'pdf',
            'renderer': 'native', 'cache_hit': False}
    if record['preview_kind'] not in RENDERABLE_PREVIEW_KINDS:
        raise StorageValidationError('Rendered previews are only available for PDF and Office-style files.')
    extension = 'png' if thumbnail else 'pdf'
    cache_path = _preview_cache_root(data_root) / f'{_preview_cache_key(path, record)}.{extension}'
    cache_hit = _ensure_cached_conversion(path, cache_path, output_extension=extension)
    return cache_path, {'file': record, 'content_type': 'image/png' if thumbnail else 'application/pdf',
        'preview_kind': 'image' if thumbnail else 'pdf', 'renderer': 'libreoffice', 'cache_hit': cache_hit}


def rendered_preview_payload(*, path: Path, root: Path, role: str, data_root: Path,
                             stream: bool = False, app_id: str = 'storage', thumbnail: bool = False) -> dict:
    """Browser callers receive an authenticated media URL; CLI callers retain bounded inline data."""
    preview_path, payload = rendered_preview_path(path=path, root=root, role=role, data_root=data_root, thumbnail=thumbnail)
    if stream:
        params = urlencode({'role': role, 'relative_path': payload['file']['relative_path'],
            'preview': 'thumbnail' if thumbnail else 'rendered',
            'preview_version': _preview_cache_key(path, payload['file'])})
        return {**payload, 'stream_url': f'/api/apps/{app_id}/media?{params}'}
    if preview_path.stat().st_size > MAX_RENDER_SOURCE_BYTES:
        raise StorageValidationError('Rendered preview is too large for an inline response.')
    return {**payload, 'content_base64': b64encode(preview_path.read_bytes()).decode('ascii')}


def rendered_thumbnail_payload(*, path: Path, root: Path, role: str, data_root: Path,
                               stream: bool = False, app_id: str = 'storage') -> dict:
    return rendered_preview_payload(path=path, root=root, role=role, data_root=data_root,
        stream=stream, app_id=app_id, thumbnail=True)


def rendered_media_payload(*, path: Path, root: Path, role: str, data_root: Path, body: dict) -> dict:
    record = file_record(role=role, root=root, path=path.resolve())
    version = _preview_cache_key(path, record)
    if body.get('preview_version') and body['preview_version'] != version:
        raise StorageValidationError('The preview source changed; refresh the preview.')
    thumbnail = body['preview'] == 'thumbnail'
    preview_path, payload = rendered_preview_path(path=path, root=root, role=role, data_root=data_root, thumbnail=thumbnail)
    return {'file': record, 'file_response': {'path': str(preview_path), 'content_type': payload['content_type'],
        'file_name': path.stem + ('.png' if thumbnail else '.pdf'), 'etag': version,
        'download': False, 'cache_control': 'private, no-store'}}
