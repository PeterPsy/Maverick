"""Text extraction helpers for Storage file previews and document reads."""

from __future__ import annotations

import csv
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree


MAX_TEXT_PREVIEW_CHARS = 12_000
MAX_TABLE_PREVIEW_ROWS = 200
MAX_TABLE_PREVIEW_COLUMNS = 50
MAX_PREVIEW_FILE_BYTES = 25 * 1024 * 1024
MAX_TEXT_PREVIEW_BYTES = 256 * 1024
MAX_ARCHIVE_ENTRIES = 256
MAX_ARCHIVE_DECOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_TEXT_READ_FILE_BYTES = 100 * 1024 * 1024
MAX_TEXT_READ_ARCHIVE_ENTRIES = 2048
MAX_TEXT_READ_ARCHIVE_DECOMPRESSED_BYTES = 64 * 1024 * 1024


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _trim_preview(text: str, max_chars: int | None, *, truncated: bool = False) -> str:
    collapsed = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if max_chars is None:
        return collapsed + ("…" if truncated and not collapsed.endswith("…") else "")
    if len(collapsed) <= max_chars and not truncated:
        return collapsed
    return collapsed[: max_chars - 1].rstrip() + "…"


def _text_file_preview(path: Path, max_chars: int | None) -> str:
    if max_chars is not None and max_chars <= 0:
        return ""
    byte_budget = MAX_TEXT_PREVIEW_BYTES if max_chars is None else min(MAX_TEXT_PREVIEW_BYTES, max(4096, max_chars * 4))
    with path.open("rb") as handle:
        payload = handle.read(byte_budget + 1)
    truncated = len(payload) > byte_budget or path.stat().st_size > byte_budget
    return _trim_preview(payload[:byte_budget].decode("utf-8", errors="replace"), max_chars, truncated=truncated)


def _xml_text(payload: bytes) -> str:
    root = ElementTree.fromstring(payload)
    values: list[str] = []
    for element in root.iter():
        if element.tag.endswith("}t") or element.tag == "t":
            if element.text:
                values.append(element.text)
    return " ".join(values)


def _docx_text(
    path: Path,
    *,
    max_file_bytes: int = MAX_PREVIEW_FILE_BYTES,
    max_archive_entries: int = MAX_ARCHIVE_ENTRIES,
    max_decompressed_bytes: int = MAX_ARCHIVE_DECOMPRESSED_BYTES,
) -> str:
    _validate_file_budget(path, max_file_bytes=max_file_bytes)
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(
            archive,
            max_entries=max_archive_entries,
            max_decompressed_bytes=max_decompressed_bytes,
        )
        return _xml_text(_read_archive_member(archive, "word/document.xml", max_decompressed_bytes=max_decompressed_bytes))


def _pptx_text(
    path: Path,
    *,
    max_file_bytes: int = MAX_PREVIEW_FILE_BYTES,
    max_archive_entries: int = MAX_ARCHIVE_ENTRIES,
    max_decompressed_bytes: int = MAX_ARCHIVE_DECOMPRESSED_BYTES,
) -> str:
    _validate_file_budget(path, max_file_bytes=max_file_bytes)
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(
            archive,
            max_entries=max_archive_entries,
            max_decompressed_bytes=max_decompressed_bytes,
        )
        slide_names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
        return "\n".join(_xml_text(_read_archive_member(archive, name, max_decompressed_bytes=max_decompressed_bytes)) for name in slide_names)


def _xlsx_shared_strings(archive: zipfile.ZipFile, *, max_decompressed_bytes: int = MAX_ARCHIVE_DECOMPRESSED_BYTES) -> list[str]:
    try:
        payload = _read_archive_member(archive, "xl/sharedStrings.xml", max_decompressed_bytes=max_decompressed_bytes)
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


def _xlsx_column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference.upper())
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - ord("A") + 1)
    return max(index - 1, 0)


def _xlsx_text(
    path: Path,
    *,
    max_file_bytes: int = MAX_PREVIEW_FILE_BYTES,
    max_archive_entries: int = MAX_ARCHIVE_ENTRIES,
    max_decompressed_bytes: int = MAX_ARCHIVE_DECOMPRESSED_BYTES,
) -> str:
    _validate_file_budget(path, max_file_bytes=max_file_bytes)
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(
            archive,
            max_entries=max_archive_entries,
            max_decompressed_bytes=max_decompressed_bytes,
        )
        shared_strings = _xlsx_shared_strings(archive, max_decompressed_bytes=max_decompressed_bytes)
        sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        rows: list[str] = []
        for name in sheet_names:
            root = ElementTree.fromstring(_read_archive_member(archive, name, max_decompressed_bytes=max_decompressed_bytes))
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


def _odt_text(
    path: Path,
    *,
    max_file_bytes: int = MAX_PREVIEW_FILE_BYTES,
    max_archive_entries: int = MAX_ARCHIVE_ENTRIES,
    max_decompressed_bytes: int = MAX_ARCHIVE_DECOMPRESSED_BYTES,
) -> str:
    _validate_file_budget(path, max_file_bytes=max_file_bytes)
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(
            archive,
            max_entries=max_archive_entries,
            max_decompressed_bytes=max_decompressed_bytes,
        )
        root = ElementTree.fromstring(_read_archive_member(archive, "content.xml", max_decompressed_bytes=max_decompressed_bytes))
    blocks: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) not in {"h", "p", "list-item"}:
            continue
        text = " ".join("".join(element.itertext()).split())
        if text:
            blocks.append(text)
    return "\n".join(blocks)


def _validate_file_budget(path: Path, *, max_file_bytes: int = MAX_PREVIEW_FILE_BYTES) -> None:
    if path.stat().st_size > max_file_bytes:
        raise ValueError("file is too large for text extraction.")


def _validate_archive_budget(
    archive: zipfile.ZipFile,
    *,
    max_entries: int = MAX_ARCHIVE_ENTRIES,
    max_decompressed_bytes: int = MAX_ARCHIVE_DECOMPRESSED_BYTES,
) -> None:
    entries = archive.infolist()
    if len(entries) > max_entries:
        raise ValueError("archive contains too many entries for text extraction.")
    total = 0
    for entry in entries:
        total += int(entry.file_size or 0)
        if total > max_decompressed_bytes:
            raise ValueError("archive exceeds decompressed text extraction budget.")


def _read_archive_member(
    archive: zipfile.ZipFile,
    name: str,
    *,
    max_decompressed_bytes: int = MAX_ARCHIVE_DECOMPRESSED_BYTES,
) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > max_decompressed_bytes:
        raise ValueError("archive member exceeds text extraction budget.")
    return archive.read(name)


def _limited_rows(rows: list[list[str]], max_rows: int | None, max_columns: int | None) -> tuple[list[list[str]], bool, bool]:
    row_limited = max_rows is not None and len(rows) > max_rows
    limited_rows = rows[:max_rows] if max_rows is not None else rows
    column_limited = max_columns is not None and any(len(row) > max_columns for row in rows)
    normalized: list[list[str]] = []
    for row in limited_rows:
        values = row[:max_columns] if max_columns is not None else row
        normalized.append([str(value) for value in values])
    return normalized, row_limited, column_limited


def _csv_table(path: Path, max_rows: int | None, max_columns: int | None) -> dict:
    _validate_file_budget(path)
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(handle, dialect)
        for row in reader:
            rows.append([cell.strip() for cell in row])
            if max_rows is not None and len(rows) > max_rows:
                break
    limited_rows, row_limited, column_limited = _limited_rows(rows, max_rows, max_columns)
    return {
        "sheets": [
            {
                "name": path.stem or "CSV",
                "rows": limited_rows,
                "truncated_rows": row_limited,
                "truncated_columns": column_limited,
            }
        ]
    }


def _xlsx_table(path: Path, max_rows: int | None, max_columns: int | None) -> dict:
    _validate_file_budget(path)
    with zipfile.ZipFile(path) as archive:
        _validate_archive_budget(archive)
        shared_strings = _xlsx_shared_strings(archive)
        sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        sheets: list[dict] = []
        sheet_limit = 6 if max_rows is not None or max_columns is not None else None
        for sheet_index, name in enumerate(sheet_names[:sheet_limit]):
            root = ElementTree.fromstring(_read_archive_member(archive, name))
            rows: list[list[str]] = []
            for row in root.iter():
                if _local_name(row.tag) != "row":
                    continue
                cells_by_index: dict[int, str] = {}
                for sequential_index, cell in enumerate(child for child in row if _local_name(child.tag) == "c"):
                    column_index = _xlsx_column_index(cell.attrib.get("r", "")) if cell.attrib.get("r") else sequential_index
                    cells_by_index[column_index] = _xlsx_cell_text(cell, shared_strings)
                if not cells_by_index:
                    continue
                width = max(cells_by_index) + 1
                if max_columns is not None:
                    width = min(width, max_columns)
                rows.append([cells_by_index.get(index, "") for index in range(width)])
                if max_rows is not None and len(rows) > max_rows:
                    break
            limited_rows, row_limited, column_limited = _limited_rows(rows, max_rows, max_columns)
            sheets.append(
                {
                    "name": f"Sheet {sheet_index + 1}",
                    "rows": limited_rows,
                    "truncated_rows": row_limited,
                    "truncated_columns": column_limited,
                }
            )
        return {"sheets": sheets}


def extract_table_preview(path: Path, preview_kind: str, max_rows: int | None = MAX_TABLE_PREVIEW_ROWS, max_columns: int | None = MAX_TABLE_PREVIEW_COLUMNS) -> dict:
    suffix = path.suffix.lower()
    if (max_rows is not None and max_rows <= 0) or (max_columns is not None and max_columns <= 0):
        return {"sheets": []}
    try:
        if suffix == ".csv":
            return _csv_table(path, max_rows, max_columns)
        if suffix == ".xlsx" or preview_kind == "spreadsheet":
            return _xlsx_table(path, max_rows, max_columns)
    except (ValueError, csv.Error, KeyError, ElementTree.ParseError, zipfile.BadZipFile, OSError, UnicodeDecodeError):
        return {"sheets": []}
    return {"sheets": []}


def extract_text_preview(path: Path, preview_kind: str, max_chars: int | None = MAX_TEXT_PREVIEW_CHARS) -> str:
    suffix = path.suffix.lower()
    if preview_kind in {"text", "markdown"}:
        return _text_file_preview(path, max_chars)
    try:
        if suffix == ".docx":
            return _trim_preview(_docx_text(path), max_chars)
        if suffix == ".pptx":
            return _trim_preview(_pptx_text(path), max_chars)
        if suffix == ".xlsx":
            return _trim_preview(_xlsx_text(path), max_chars)
        if suffix == ".odt":
            return _trim_preview(_odt_text(path), max_chars)
    except (ValueError, KeyError, ElementTree.ParseError, zipfile.BadZipFile, OSError, UnicodeDecodeError):
        return ""
    return ""


def text_content_supported(path: Path, preview_kind: str) -> bool:
    suffix = path.suffix.lower()
    return preview_kind in {"text", "markdown"} or suffix in {".docx", ".pptx", ".xlsx", ".odt"}


def extract_text_content(path: Path, preview_kind: str) -> str:
    suffix = path.suffix.lower()
    if preview_kind in {"text", "markdown"}:
        _validate_file_budget(path, max_file_bytes=MAX_TEXT_READ_FILE_BYTES)
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        return _docx_text(
            path,
            max_file_bytes=MAX_TEXT_READ_FILE_BYTES,
            max_archive_entries=MAX_TEXT_READ_ARCHIVE_ENTRIES,
            max_decompressed_bytes=MAX_TEXT_READ_ARCHIVE_DECOMPRESSED_BYTES,
        )
    if suffix == ".pptx":
        return _pptx_text(
            path,
            max_file_bytes=MAX_TEXT_READ_FILE_BYTES,
            max_archive_entries=MAX_TEXT_READ_ARCHIVE_ENTRIES,
            max_decompressed_bytes=MAX_TEXT_READ_ARCHIVE_DECOMPRESSED_BYTES,
        )
    if suffix == ".xlsx":
        return _xlsx_text(
            path,
            max_file_bytes=MAX_TEXT_READ_FILE_BYTES,
            max_archive_entries=MAX_TEXT_READ_ARCHIVE_ENTRIES,
            max_decompressed_bytes=MAX_TEXT_READ_ARCHIVE_DECOMPRESSED_BYTES,
        )
    if suffix == ".odt":
        return _odt_text(
            path,
            max_file_bytes=MAX_TEXT_READ_FILE_BYTES,
            max_archive_entries=MAX_TEXT_READ_ARCHIVE_ENTRIES,
            max_decompressed_bytes=MAX_TEXT_READ_ARCHIVE_DECOMPRESSED_BYTES,
        )
    return ""
