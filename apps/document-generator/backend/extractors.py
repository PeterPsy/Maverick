"""Workspace document text extraction helpers."""

from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any
import zipfile
import zlib

from errors import DocumentValidationError


SUPPORTED_EXTRACT_FORMATS = {"pdf", "docx", "pptx", "xlsx"}
DEFAULT_MAX_CHARS = 50000
MAX_CHARS_LIMIT = 200000
MAX_EXTRACT_FILE_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 256
MAX_ARCHIVE_DECOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_PDF_STREAM_BYTES = 4 * 1024 * 1024


def extract_text_from_workspace_file(uploaded_root: Path | None, generated_root: Path, body: dict[str, Any]) -> dict[str, Any]:
    workspace_relative_path = str(body.get("workspace_relative_path") or "").strip()
    if not workspace_relative_path:
        raise DocumentValidationError("workspace_relative_path is required.")
    target = resolve_workspace_file(uploaded_root, generated_root, workspace_relative_path)
    file_format = _format_from_path(target)
    if file_format not in SUPPORTED_EXTRACT_FORMATS:
        raise DocumentValidationError(f"Unsupported extraction format `{file_format}`.")
    if target.stat().st_size > MAX_EXTRACT_FILE_BYTES:
        raise DocumentValidationError("workspace file is too large for text extraction.")

    max_chars = _normalize_max_chars(body.get("max_chars"))
    text = _extract_by_format(target, file_format)
    normalized = _normalize_text(text)
    truncated = len(normalized) > max_chars
    if truncated:
        normalized = normalized[:max_chars].rstrip()

    return {
        "document": {
            "workspace_relative_path": workspace_relative_path,
            "filename": target.name,
            "format": file_format,
            "size_bytes": target.stat().st_size,
        },
        "text": normalized,
        "text_length": len(normalized),
        "truncated": truncated,
    }


def resolve_workspace_file(uploaded_root: Path | None, generated_root: Path, workspace_relative_path: str) -> Path:
    if "\x00" in workspace_relative_path:
        raise DocumentValidationError("workspace_relative_path contains an invalid character.")
    if workspace_relative_path.startswith("storage/generated/"):
        return _resolve_under_root(generated_root, workspace_relative_path.removeprefix("storage/generated/"))
    if workspace_relative_path.startswith("storage/uploaded/"):
        if uploaded_root is None:
            raise DocumentValidationError("uploaded storage is unavailable for this surface.")
        return _resolve_under_root(uploaded_root, workspace_relative_path.removeprefix("storage/uploaded/"))
    raise DocumentValidationError("workspace_relative_path must be under storage/generated or storage/uploaded.")


def _resolve_under_root(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise DocumentValidationError("workspace_relative_path escapes workspace storage.")
    root_path = root.resolve()
    target = (root_path / relative).resolve()
    if root_path != target and root_path not in target.parents:
        raise DocumentValidationError("workspace_relative_path escapes workspace storage.")
    if not target.is_file():
        raise DocumentValidationError("workspace file does not exist.")
    return target


def _normalize_max_chars(raw_value: object) -> int:
    try:
        value = int(raw_value or DEFAULT_MAX_CHARS)
    except (TypeError, ValueError):
        raise DocumentValidationError("max_chars must be an integer.") from None
    return max(1, min(value, MAX_CHARS_LIMIT))


def _format_from_path(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _extract_by_format(path: Path, file_format: str) -> str:
    if file_format == "docx":
        return extract_docx_text(path)
    if file_format == "pptx":
        return extract_pptx_text(path)
    if file_format == "xlsx":
        return extract_xlsx_text(path)
    if file_format == "pdf":
        return extract_pdf_text(path)
    raise DocumentValidationError(f"Unsupported extraction format `{file_format}`.")


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(archive)
        names = ["word/document.xml"]
        names.extend(sorted(name for name in archive.namelist() if name.startswith("word/header") or name.startswith("word/footer")))
        chunks = [_xml_text(_read_archive_member(archive, name)) for name in names if name in archive.namelist()]
    return "\n".join(chunk for chunk in chunks if chunk)


def extract_pptx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(archive)
        slide_names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=_numeric_suffix,
        )
        chunks = [_xml_text(_read_archive_member(archive, name)) for name in slide_names]
    return "\n\n".join(chunk for chunk in chunks if chunk)


def extract_xlsx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(archive)
        shared_strings = _xlsx_shared_strings(archive)
        sheet_names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
            key=_numeric_suffix,
        )
        sheets = [_xlsx_sheet_text(_read_archive_member(archive, name), shared_strings) for name in sheet_names]
    return "\n\n".join(sheet for sheet in sheets if sheet)


def _xml_text(raw_xml: bytes) -> str:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return ""
    values = [unescape((element.text or "").strip()) for element in root.iter() if element.tag.endswith("}t") and element.text]
    return "\n".join(value for value in values if value)


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    try:
        root = ET.fromstring(_read_archive_member(archive, "xl/sharedStrings.xml"))
    except ET.ParseError:
        return []
    strings: list[str] = []
    for item in root:
        values = [(element.text or "") for element in item.iter() if element.tag.endswith("}t") and element.text]
        strings.append("".join(values))
    return strings


def _xlsx_sheet_text(raw_xml: bytes, shared_strings: list[str]) -> str:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return ""
    rows: list[str] = []
    for row in root.iter():
        if not row.tag.endswith("}row"):
            continue
        cells = [_xlsx_cell_text(cell, shared_strings) for cell in row if cell.tag.endswith("}c")]
        rows.append("\t".join(cells).rstrip())
    return "\n".join(row for row in rows if row)


def _xlsx_cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        values = [(element.text or "") for element in cell.iter() if element.tag.endswith("}t") and element.text]
        return "".join(values)
    value = next((element.text or "" for element in cell if element.tag.endswith("}v")), "")
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return ""
    return value


def _numeric_suffix(path: str) -> tuple[int, str]:
    match = re.search(r"(\d+)(?=\.[^.]+$)", path)
    return (int(match.group(1)) if match else 0, path)


def extract_pdf_text(path: Path) -> str:
    data = path.read_bytes()
    objects = _pdf_objects(data)
    cmaps = {object_id: _parse_cmap(_decode_pdf_stream(raw)) for object_id, raw in objects.items() if b"beginbfchar" in _decode_pdf_stream(raw) or b"beginbfrange" in _decode_pdf_stream(raw)}
    font_maps = _pdf_font_maps(objects, cmaps)
    chunks: list[str] = []
    for raw in objects.values():
        stream = _decode_pdf_stream(raw)
        if b"BT" not in stream or (b"Tj" not in stream and b"TJ" not in stream):
            continue
        chunks.extend(_extract_pdf_content_text(stream, font_maps))
    return "\n".join(chunk for chunk in chunks if chunk.strip())


def _pdf_objects(data: bytes) -> dict[int, bytes]:
    objects: dict[int, bytes] = {}
    for match in re.finditer(rb"(?m)(\d+)\s+0\s+obj\b(.*?)\bendobj", data, re.S):
        objects[int(match.group(1))] = match.group(2)
    return objects


def _decode_pdf_stream(raw_object: bytes) -> bytes:
    match = re.search(rb"\bstream\r?\n(.*?)\r?\nendstream\b", raw_object, re.S)
    if not match:
        return raw_object
    stream = match.group(1)
    if b"/FlateDecode" not in raw_object:
        return stream
    try:
        decompressor = zlib.decompressobj()
        data = decompressor.decompress(stream, MAX_PDF_STREAM_BYTES + 1)
        if len(data) > MAX_PDF_STREAM_BYTES:
            raise DocumentValidationError("PDF stream exceeds extraction budget.")
        return data
    except zlib.error:
        return stream


def _validate_archive_budget(archive: zipfile.ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise DocumentValidationError("archive contains too many entries for text extraction.")
    total = 0
    for entry in entries:
        total += int(entry.file_size or 0)
        if total > MAX_ARCHIVE_DECOMPRESSED_BYTES:
            raise DocumentValidationError("archive exceeds decompressed extraction budget.")


def _read_archive_member(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > MAX_ARCHIVE_DECOMPRESSED_BYTES:
        raise DocumentValidationError("archive member exceeds extraction budget.")
    return archive.read(name)


def _parse_cmap(raw_cmap: bytes) -> dict[int, str]:
    text = raw_cmap.decode("latin-1", errors="ignore")
    mapping: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for source, target in re.findall(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>", block):
            mapping[int(source, 16)] = _decode_pdf_unicode_hex(target)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for start, end, target_start in re.findall(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>", block):
            start_int = int(start, 16)
            end_int = int(end, 16)
            target_int = int(target_start, 16)
            for offset, source_int in enumerate(range(start_int, end_int + 1)):
                mapping[source_int] = chr(target_int + offset)
    return mapping


def _decode_pdf_unicode_hex(value: str) -> str:
    raw = bytes.fromhex(value)
    if len(raw) >= 2 and len(raw) % 2 == 0:
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1", errors="replace")


def _pdf_font_maps(objects: dict[int, bytes], cmaps: dict[int, dict[int, str]]) -> dict[str, dict[int, str]]:
    font_object_maps: dict[int, dict[int, str]] = {}
    for object_id, raw in objects.items():
        match = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", raw)
        if match:
            font_object_maps[object_id] = cmaps.get(int(match.group(1)), {})

    font_maps: dict[str, dict[int, str]] = {}
    for raw in objects.values():
        for font_block in re.findall(rb"/Font\s*<<(.*?)>>", raw, re.S):
            for name, object_ref in re.findall(rb"/([A-Za-z0-9_.-]+)\s+(\d+)\s+0\s+R", font_block):
                cmap = font_object_maps.get(int(object_ref))
                if cmap:
                    font_maps[f"/{name.decode('latin-1')}"] = cmap
    return font_maps


def _extract_pdf_content_text(stream: bytes, font_maps: dict[str, dict[int, str]]) -> list[str]:
    text = stream.decode("latin-1", errors="ignore")
    pattern = re.compile(
        r"(?P<font>/[A-Za-z0-9_.-]+)\s+[-+]?\d+(?:\.\d+)?\s+Tf|"
        r"(?P<array>\[(?:.|\n)*?\])\s*TJ|"
        r"(?P<hex><[0-9A-Fa-f\s]+>)\s*Tj|"
        r"(?P<literal>\((?:\\.|[^\\)])*\))\s*Tj",
        re.S,
    )
    current_cmap: dict[int, str] = {}
    chunks: list[str] = []
    for match in pattern.finditer(text):
        font = match.group("font")
        if font:
            current_cmap = font_maps.get(font, {})
            continue
        if match.group("array"):
            chunks.append(_decode_pdf_text_array(match.group("array"), current_cmap))
        elif match.group("hex"):
            chunks.append(_decode_pdf_hex_string(match.group("hex"), current_cmap))
        elif match.group("literal"):
            chunks.append(_decode_pdf_literal_string(match.group("literal")))
    return chunks


def _decode_pdf_text_array(array: str, cmap: dict[int, str]) -> str:
    parts: list[str] = []
    for hex_value in re.findall(r"<([0-9A-Fa-f\s]+)>", array):
        parts.append(_decode_pdf_hex_bytes(hex_value, cmap))
    for literal_value in re.findall(r"\((?:\\.|[^\\)])*\)", array):
        parts.append(_decode_pdf_literal_string(literal_value))
    return "".join(parts)


def _decode_pdf_hex_string(value: str, cmap: dict[int, str]) -> str:
    return _decode_pdf_hex_bytes(value.strip("<>"), cmap)


def _decode_pdf_hex_bytes(value: str, cmap: dict[int, str]) -> str:
    clean = re.sub(r"\s+", "", value)
    if len(clean) % 2:
        clean += "0"
    raw = bytes.fromhex(clean)
    if cmap:
        return "".join(cmap.get(byte, "") for byte in raw)
    try:
        return raw.decode("utf-16-be")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _decode_pdf_literal_string(value: str) -> str:
    raw = value[1:-1]
    raw = raw.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
    raw = raw.replace(r"\n", "\n").replace(r"\r", "\r").replace(r"\t", "\t").replace(r"\b", "\b").replace(r"\f", "\f")
    return raw


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line
        if blank and previous_blank:
            continue
        normalized.append(line)
        previous_blank = blank
    return "\n".join(normalized).strip()
