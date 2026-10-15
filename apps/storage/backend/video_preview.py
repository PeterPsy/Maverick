"""Versioned browser playback derivatives; source media remains unchanged."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from errors import StorageValidationError
from preview_conversion import cache_lock, conversion_slot


MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_DURATION_SECONDS = 600
MAX_CACHE_BYTES = 300 * 1024 * 1024
MAX_CACHE_FILES = 120
CONVERSION_TIMEOUT_SECONDS = 60


def browser_video_response(*, data_root: Path, file_response: dict) -> dict:
    if file_response.get('download'):
        return file_response
    source = Path(file_response['path']).resolve()
    before = _signature(source)
    if before[0] > MAX_SOURCE_BYTES:
        raise StorageValidationError('Video is too large for a browser playback preview.')
    key = hashlib.sha256(repr(('h264-v1', str(source), before)).encode()).hexdigest()
    cache_root = data_root / 'video_previews'
    target = cache_root / f'{key}.mp4'
    native = cache_root / f'{key}.native'
    with cache_lock(target):
        if native.is_file():
            return file_response
        if not target.is_file():
            with conversion_slot(cache_root, timeout=CONVERSION_TIMEOUT_SECONDS):
                if _native_browser_video(source):
                    if _signature(source) != before:
                        raise StorageValidationError('Video changed during preview preparation; retry.')
                    native.touch()
                    _evict_cache(cache_root, keep=native)
                    return file_response
                temporary = target.with_name(f'.{key}-{uuid4().hex}.mp4')
                try:
                    _convert_video(source, temporary)
                    if _signature(source) != before:
                        raise StorageValidationError('Video changed during conversion; retry.')
                    if not temporary.is_file() or temporary.stat().st_size == 0:
                        raise StorageValidationError('Video conversion did not produce a playback preview.')
                    if temporary.stat().st_size >= MAX_SOURCE_BYTES:
                        raise StorageValidationError('The browser video preview exceeded its size budget.')
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
                _evict_cache(cache_root, keep=target)
    return {**file_response, 'path': str(target), 'content_type': 'video/mp4',
            'file_name': str(Path(file_response.get('file_name') or 'video').with_suffix('.mp4')),
            'etag': f'browser-video-{key}', 'cache_control': 'private, max-age=60'}


def _signature(path: Path) -> tuple:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino


def _binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise StorageValidationError(f'{name} is required for browser video previews.')
    return binary


def _native_browser_video(source: Path) -> bool:
    try:
        result = subprocess.run([
            _binary('ffprobe'), '-v', 'error', '-show_entries',
            'stream=codec_type,codec_name,pix_fmt:format=duration', '-of', 'json', str(source),
        ], capture_output=True, text=True, timeout=10, check=True)
        metadata = json.loads(result.stdout)
        duration = float(metadata.get('format', {}).get('duration') or 0)
        streams = metadata.get('streams', [])
    except (subprocess.SubprocessError, ValueError, OSError) as error:
        raise StorageValidationError('Storage could not inspect the video for browser playback.') from error
    if duration <= 0 or duration > MAX_DURATION_SECONDS:
        raise StorageValidationError('Browser video previews require a duration of at most 10 minutes.')
    videos = [stream for stream in streams if stream.get('codec_type') == 'video']
    if not videos:
        raise StorageValidationError('The selected media has no video stream.')
    return all(stream.get('codec_name') in {'h264', 'vp8', 'vp9', 'av1'}
               and stream.get('pix_fmt') == 'yuv420p' for stream in videos) and all(
        stream.get('codec_name') in {'aac', 'mp3', 'opus', 'vorbis'}
        for stream in streams if stream.get('codec_type') == 'audio')


def _convert_video(source: Path, target: Path) -> None:
    try:
        subprocess.run([
            _binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
            '-threads', '1', '-i', str(source), '-map', '0:v:0', '-map', '0:a:0?',
            '-vf', "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
            '-filter_threads', '1', '-c:v', 'libx264', '-threads', '1', '-preset', 'veryfast',
            '-crf', '23', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
            '-movflags', '+faststart', '-fs', str(MAX_SOURCE_BYTES), '-f', 'mp4', str(target),
        ], capture_output=True, timeout=CONVERSION_TIMEOUT_SECONDS, check=True)
    except (subprocess.SubprocessError, OSError) as error:
        raise StorageValidationError('Storage could not prepare the browser video preview; retry.') from error


def _evict_cache(cache_root: Path, *, keep: Path) -> None:
    files = sorted((path for path in cache_root.iterdir() if path.suffix in {'.mp4', '.native'}),
                   key=lambda path: path.stat().st_mtime_ns, reverse=True)
    total = keep.stat().st_size
    count = 1
    for path in files:
        if path == keep:
            continue
        total += path.stat().st_size
        count += 1
        if count > MAX_CACHE_FILES or total > MAX_CACHE_BYTES:
            path.unlink(missing_ok=True)
