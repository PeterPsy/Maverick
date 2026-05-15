"""PDF text extraction helpers for simple generated PDFs."""

from __future__ import annotations

from pathlib import Path
import re
import zlib

from errors import DocumentValidationError


MAX_PDF_STREAM_BYTES = 4 * 1024 * 1024


def extract_pdf_text(path: Path) -> str:
    data = path.read_bytes()
    objects = _pdf_objects(data)
    cmaps = {
        object_id: _parse_cmap(_decode_pdf_stream(raw))
        for object_id, raw in objects.items()
        if b"beginbfchar" in _decode_pdf_stream(raw) or b"beginbfrange" in _decode_pdf_stream(raw)
    }
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
