"""DOCX, PPTX, and XLSX text extraction helpers."""

from __future__ import annotations

from html import unescape
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from errors import DocumentValidationError


MAX_ARCHIVE_ENTRIES = 256
MAX_ARCHIVE_DECOMPRESSED_BYTES = 8 * 1024 * 1024


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


def extract_odt_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(archive)
        raw_xml = _read_archive_member(archive, "content.xml")
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return ""
    blocks: list[str] = []
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name not in {"h", "p", "list-item"}:
            continue
        text = " ".join("".join(element.itertext()).split())
        if text:
            blocks.append(text)
    return "\n".join(blocks)


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
