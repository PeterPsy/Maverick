"""Text extraction helpers for Gallery file previews."""

from __future__ import annotations

from pathlib import Path
import zipfile
from xml.etree import ElementTree


MAX_TEXT_PREVIEW_CHARS = 12_000


def _trim_preview(text: str, max_chars: int) -> str:
    collapsed = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 1].rstrip() + "…"


def _xml_text(payload: bytes) -> str:
    root = ElementTree.fromstring(payload)
    values: list[str] = []
    for element in root.iter():
        if element.tag.endswith("}t") or element.tag == "t":
            if element.text:
                values.append(element.text)
    return " ".join(values)


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return _xml_text(archive.read("word/document.xml"))


def _pptx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
        return "\n".join(_xml_text(archive.read(name)) for name in slide_names)


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        payload = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(payload)
    strings: list[str] = []
    for item in root.iter():
        if item.tag.endswith("}si") or item.tag == "si":
            values = [node.text or "" for node in item.iter() if node.tag.endswith("}t") or node.tag == "t"]
            strings.append("".join(values))
    return strings


def _xlsx_cell_text(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    values = [node.text or "" for node in cell.iter() if node.tag.endswith("}v") or node.tag == "v"]
    if cell_type == "s" and values:
        try:
            return shared_strings[int(values[0])]
        except (IndexError, ValueError):
            return values[0]
    inline_values = [node.text or "" for node in cell.iter() if node.tag.endswith("}t") or node.tag == "t"]
    if inline_values:
        return "".join(inline_values)
    return values[0] if values else ""


def _xlsx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        rows: list[str] = []
        for name in sheet_names:
            root = ElementTree.fromstring(archive.read(name))
            for row in root.iter():
                if not (row.tag.endswith("}row") or row.tag == "row"):
                    continue
                cells = [
                    _xlsx_cell_text(cell, shared_strings)
                    for cell in row
                    if cell.tag.endswith("}c") or cell.tag == "c"
                ]
                row_text = " | ".join(value for value in cells if value)
                if row_text:
                    rows.append(row_text)
        return "\n".join(rows)


def extract_text_preview(path: Path, preview_kind: str, max_chars: int = MAX_TEXT_PREVIEW_CHARS) -> str:
    suffix = path.suffix.lower()
    if preview_kind in {"text", "markdown"}:
        return _trim_preview(path.read_text(encoding="utf-8", errors="replace"), max_chars)
    try:
        if suffix == ".docx":
            return _trim_preview(_docx_text(path), max_chars)
        if suffix == ".pptx":
            return _trim_preview(_pptx_text(path), max_chars)
        if suffix == ".xlsx":
            return _trim_preview(_xlsx_text(path), max_chars)
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile, OSError, UnicodeDecodeError):
        return ""
    return ""
