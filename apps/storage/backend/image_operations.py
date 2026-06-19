"""Image inspection and composition helpers for Storage."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from errors import StorageValidationError
from inventory import upsert_file_record
from store_files_paths import (
    atomic_write_bytes,
    enforce_storage_budget,
    hash_file,
    normalize_write_mode,
    prepare_write_target,
    reference_from_payload,
    resolve_storage_file,
    safe_file_name,
    safe_folder_relative_path,
    storage_root_for_role,
    storage_write_lock,
    write_audit_payload,
)


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
SUPPORTED_OUTPUT_FORMATS = {"jpg": ("jpg", "image/jpeg"), "jpeg": ("jpg", "image/jpeg"), "png": ("png", "image/png")}
DEFAULT_TARGET_FOLDER = "image-ops"
DEFAULT_OUTPUT_HEIGHT = 1800
MAX_OUTPUT_HEIGHT = 5000
FFPROBE_TIMEOUT_SECONDS = 15
FFMPEG_TIMEOUT_SECONDS = 120
SAFE_BACKGROUND_COLOR_NAMES = {
    "black",
    "blue",
    "brown",
    "cyan",
    "gray",
    "green",
    "grey",
    "magenta",
    "orange",
    "pink",
    "purple",
    "red",
    "white",
    "yellow",
}
HEX_BACKGROUND_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def image_inspect_payload(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    images = [
        _public_inspection(_inspect_ref(ref, data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root))
        for ref in _image_refs_from_body(body, minimum=1, maximum=20)
    ]
    return {"status": "ok", "images": images, "image_count": len(images)}


def image_dependencies_health() -> dict[str, Any]:
    dependencies = {
        "ffprobe": _binary_dependency_health("ffprobe"),
        "ffmpeg": _binary_dependency_health("ffmpeg"),
    }
    inspect_available = bool(dependencies["ffprobe"]["available"])
    compose_available = bool(dependencies["ffprobe"]["available"] and dependencies["ffmpeg"]["available"])
    return {
        "available": compose_available,
        "dependencies": dependencies,
        "operations": {
            "image.inspect": {"available": inspect_available, "requires": ["ffprobe"]},
            "image.compose_pair": {"available": compose_available, "requires": ["ffprobe", "ffmpeg"]},
        },
    }


def image_compose_pair_payload(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    refs = _image_refs_from_body(body, minimum=2, maximum=2)
    sources = [
        _inspect_ref(ref, data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)
        for ref in refs
    ]
    output_format, content_type = _output_format(body)
    target_height = _target_height(body, sources)
    target_folder, file_name = _target_location(body, output_format=output_format)
    requested_relative_path = (target_folder / file_name).as_posix()
    root = storage_root_for_role(role="generated", uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    requested_target = (root / requested_relative_path).resolve()
    mode = normalize_write_mode(body.get("mode") or "create", operation="image.compose_pair")
    with storage_write_lock(data_root):
        target = prepare_write_target(
            root=root,
            requested_target=requested_target,
            mode=mode,
            operation="image.compose_pair",
            confirm=body.get("confirm"),
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        previous_sha256 = hash_file(target) if target.exists() and target.is_file() else ""
        composed_bytes, output_image = _compose_side_by_side(
            [Path(str(item["local_path"])) for item in sources],
            target_dir=target.parent,
            output_format=output_format,
            target_height=target_height,
            background_color=_background_color(body.get("background_color")),
        )
        enforce_storage_budget(uploaded_root=uploaded_root, generated_root=generated_root, target=target, payload_size=len(composed_bytes))
        atomic_write_bytes(target, composed_bytes)
        sha256 = hash_file(target)
        record = upsert_file_record(data_root=data_root, role="generated", root=root, path=target.resolve(), sha256=sha256)
    return {
        "status": "created",
        "operation": "image.compose_pair",
        "file": record,
        "workspace_relative_path": record["workspace_relative_path"],
        "content_type": content_type,
        "source_images": [_public_source(item) for item in sources],
        "output_image": {
            **output_image,
            "content_type": content_type,
            "sha256": sha256,
            "size_bytes": int(record["size_bytes"]),
        },
        "audit": write_audit_payload(
            operation="image.compose_pair",
            requested_mode=mode,
            role="generated",
            root=root,
            requested_target=requested_target,
            target=target,
            previous_sha256=previous_sha256,
            sha256=sha256,
            bytes_written=len(composed_bytes),
        ),
    }


def _image_refs_from_body(body: dict[str, Any], *, minimum: int, maximum: int) -> list[dict[str, Any]]:
    raw_images = body.get("images")
    if raw_images in (None, "") and "workspace_relative_paths" in body:
        raw_images = body.get("workspace_relative_paths")
    if raw_images in (None, "") and ("left_workspace_relative_path" in body or "right_workspace_relative_path" in body):
        raw_images = [
            {"workspace_relative_path": body.get("left_workspace_relative_path"), "label": "left"},
            {"workspace_relative_path": body.get("right_workspace_relative_path"), "label": "right"},
        ]
    if raw_images in (None, "") and "workspace_relative_path" in body:
        raw_images = [body.get("workspace_relative_path")]
    if not isinstance(raw_images, list):
        raise StorageValidationError("images must be an array of Storage file references.", operation="image")
    refs = [_normalize_image_ref(item) for item in raw_images]
    if not (minimum <= len(refs) <= maximum):
        if minimum == maximum:
            raise StorageValidationError(f"images must contain exactly {minimum} items.", operation="image")
        raise StorageValidationError(f"images must contain between {minimum} and {maximum} items.", operation="image")
    return refs


def _normalize_image_ref(item: object) -> dict[str, Any]:
    if isinstance(item, str):
        return {"workspace_relative_path": item}
    if not isinstance(item, dict):
        raise StorageValidationError("Each image reference must be a string or object.", operation="image")
    return dict(item)


def _inspect_ref(
    ref: dict[str, Any],
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
) -> dict[str, Any]:
    role, relative_path = reference_from_payload(
        role=str(ref.get("role") or ""),
        relative_path=str(ref.get("relative_path") or ""),
        workspace_relative_path=str(ref.get("workspace_relative_path") or ""),
    )
    path = resolve_storage_file(role=role, relative_path=relative_path, uploaded_root=uploaded_root, generated_root=generated_root)
    if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise StorageValidationError("Only common image files are supported for image operations.", operation="image")
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    record = upsert_file_record(data_root=data_root, role=role, root=root, path=path.resolve())
    metadata = _probe_image(path)
    return {
        **metadata,
        "label": str(ref.get("label") or "").strip(),
        "role": role,
        "relative_path": relative_path,
        "workspace_relative_path": f"storage/{role}/{relative_path}",
        "file": record,
        "local_path": str(path),
    }


def _probe_image(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise StorageValidationError("ffprobe is required for Storage image inspection.", operation="image.inspect")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height:stream_tags=rotate:stream_side_data=rotation",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        timeout=FFPROBE_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise StorageValidationError(f"Image metadata could not be read: {result.stderr.strip()[:300]}", operation="image.inspect")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise StorageValidationError("Image metadata probe returned invalid JSON.", operation="image.inspect") from error
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    stream = streams[0] if streams and isinstance(streams[0], dict) else {}
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise StorageValidationError("Image metadata did not include positive dimensions.", operation="image.inspect")
    rotation = _rotation_from_stream(stream)
    display_width, display_height = (height, width) if abs(rotation) % 180 == 90 else (width, height)
    return {
        "filename": path.name,
        "codec": str(stream.get("codec_name") or ""),
        "width": width,
        "height": height,
        "rotation_degrees": rotation,
        "display_width": display_width,
        "display_height": display_height,
        "auto_rotate_required": rotation != 0,
        "size_bytes": path.stat().st_size,
        "sha256": hash_file(path),
    }


def _rotation_from_stream(stream: dict[str, Any]) -> int:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    raw_rotation = tags.get("rotate")
    if raw_rotation in (None, ""):
        side_data = stream.get("side_data_list") if isinstance(stream.get("side_data_list"), list) else []
        for item in side_data:
            if isinstance(item, dict) and item.get("rotation") not in (None, ""):
                raw_rotation = item.get("rotation")
                break
    try:
        return int(float(str(raw_rotation or "0"))) % 360
    except ValueError:
        return 0


def _output_format(body: dict[str, Any]) -> tuple[str, str]:
    requested = str(body.get("output_format") or body.get("format") or "jpg").strip().lower().lstrip(".")
    if requested not in SUPPORTED_OUTPUT_FORMATS:
        raise StorageValidationError("output_format must be jpg or png.", operation="image.compose_pair")
    return SUPPORTED_OUTPUT_FORMATS[requested]


def _background_color(value: object) -> str:
    requested = str(value or "white").strip()
    lowered = requested.casefold()
    if lowered in SAFE_BACKGROUND_COLOR_NAMES:
        return lowered
    if HEX_BACKGROUND_COLOR_RE.fullmatch(requested):
        return requested.lower()
    raise StorageValidationError(
        "background_color must be a supported color name or #RRGGBB.",
        operation="image.compose_pair",
        allowed_values={"background_color": sorted(SAFE_BACKGROUND_COLOR_NAMES)},
        example={"background_color": "white"},
    )


def _binary_dependency_health(binary: str) -> dict[str, Any]:
    return {"available": shutil.which(binary) is not None, "binary": binary}


def _target_height(body: dict[str, Any], sources: list[dict[str, Any]]) -> int:
    raw_height = body.get("height") if "height" in body else body.get("output_height")
    if raw_height not in (None, ""):
        try:
            height = int(raw_height)
        except (TypeError, ValueError) as error:
            raise StorageValidationError("height must be an integer.", operation="image.compose_pair") from error
        if height <= 0 or height > MAX_OUTPUT_HEIGHT:
            raise StorageValidationError(f"height must be between 1 and {MAX_OUTPUT_HEIGHT}.", operation="image.compose_pair")
        return height
    source_height = max(int(item.get("display_height") or 0) for item in sources)
    return min(MAX_OUTPUT_HEIGHT, max(1, min(source_height, DEFAULT_OUTPUT_HEIGHT)))


def _target_location(body: dict[str, Any], *, output_format: str) -> tuple[Path, str]:
    workspace_relative_path = str(body.get("target_workspace_relative_path") or body.get("output_workspace_relative_path") or "").strip()
    if workspace_relative_path:
        role, relative_path = reference_from_payload(role="", relative_path="", workspace_relative_path=workspace_relative_path)
        if role != "generated":
            raise StorageValidationError("Image composition output must be under storage/generated.", operation="image.compose_pair")
        relative = Path(relative_path)
        return relative.parent if str(relative.parent) != "." else Path(), _output_file_name(relative.name, output_format=output_format)
    folder = _generated_folder_relative(body.get("target_folder") or DEFAULT_TARGET_FOLDER)
    return folder, _output_file_name(body.get("file_name") or f"composed-image.{output_format}", output_format=output_format)


def _output_file_name(value: object, *, output_format: str) -> str:
    file_name = safe_file_name(str(value or f"composed-image.{output_format}"))
    suffix = Path(file_name).suffix.lower()
    allowed = {".png"} if output_format == "png" else {".jpg", ".jpeg"}
    if suffix in allowed:
        return file_name
    stem = Path(file_name).stem or "composed-image"
    return f"{stem}.{output_format}"


def _generated_folder_relative(value: object) -> Path:
    text = str(value or "").strip().strip("/")
    if text == "storage/generated":
        return Path()
    if text.startswith("storage/generated/"):
        text = text.removeprefix("storage/generated/")
    return safe_folder_relative_path(text)


def _compose_side_by_side(
    paths: list[Path],
    *,
    target_dir: Path,
    output_format: str,
    target_height: int,
    background_color: str,
) -> tuple[bytes, dict[str, Any]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise StorageValidationError("ffmpeg is required for Storage image composition.", operation="image.compose_pair")
    suffix = f".{output_format}"
    handle = tempfile.NamedTemporaryFile(delete=False, dir=target_dir, prefix=".maverick-image-compose-", suffix=suffix)
    temp_path = Path(handle.name)
    handle.close()
    try:
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(paths[0]),
            "-i",
            str(paths[1]),
            "-filter_complex",
            (
                f"[0:v]scale=-2:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad=ceil(iw/2)*2:{target_height}:(ow-iw)/2:(oh-ih)/2:color={background_color}[left];"
                f"[1:v]scale=-2:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad=ceil(iw/2)*2:{target_height}:(ow-iw)/2:(oh-ih)/2:color={background_color}[right];"
                "[left][right]hstack=inputs=2[out]"
            ),
            "-map",
            "[out]",
            "-frames:v",
            "1",
        ]
        if output_format == "jpg":
            command.extend(["-q:v", "2"])
        command.append(str(temp_path))
        result = subprocess.run(command, text=True, capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS, check=False)
        if result.returncode != 0:
            raise StorageValidationError(f"Image composition failed: {result.stderr.strip()[:300]}", operation="image.compose_pair")
        metadata = _probe_image(temp_path)
        return temp_path.read_bytes(), {
            "width": metadata["width"],
            "height": metadata["height"],
            "display_width": metadata["display_width"],
            "display_height": metadata["display_height"],
            "rotation_degrees": metadata["rotation_degrees"],
            "format": output_format,
            "auto_rotate": True,
            "height": target_height,
        }
    finally:
        temp_path.unlink(missing_ok=True)


def _public_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": item.get("label") or "",
        "workspace_relative_path": item["workspace_relative_path"],
        "filename": item["filename"],
        "width": item["width"],
        "height": item["height"],
        "display_width": item["display_width"],
        "display_height": item["display_height"],
        "rotation_degrees": item["rotation_degrees"],
        "auto_rotate_required": item["auto_rotate_required"],
        "size_bytes": item["size_bytes"],
        "sha256": item["sha256"],
    }


def _public_inspection(item: dict[str, Any]) -> dict[str, Any]:
    return {**_public_source(item), "file": item["file"], "codec": item["codec"]}
