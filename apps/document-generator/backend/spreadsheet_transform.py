"""Deterministic spreadsheet transformations for workspace files."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from errors import DocumentValidationError
from store import save_job, utc_now
from workspace_files import resolve_workspace_file, workspace_relative_generated_path


MAX_SPREADSHEET_BYTES = 50 * 1024 * 1024
XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

ET.register_namespace("", XLSX_NS)
ET.register_namespace("r", REL_NS)


@dataclass
class WorkbookRef:
    alias: str
    workspace_relative_path: str
    path: Path
    workbook: "Workbook"


class Workbook:
    format: str

    def sheet_names(self) -> list[str]:
        raise NotImplementedError

    def get_cell(self, sheet: object, row_index: int, column: object) -> str:
        raise NotImplementedError

    def set_cell(self, sheet: object, row_index: int, column: object, value: object) -> None:
        raise NotImplementedError

    def row_indices(self, sheet: object) -> list[int]:
        raise NotImplementedError

    def save(self, target: Path) -> None:
        raise NotImplementedError


class XlsxWorkbook(Workbook):
    format = "xlsx"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._shared_strings: list[str] = []
        self._sheets: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        _ensure_file_budget(self.path)
        with ZipFile(self.path) as archive:
            names = set(archive.namelist())
            if "xl/workbook.xml" not in names:
                raise DocumentValidationError("XLSX workbook.xml is missing.")
            self._shared_strings = _xlsx_shared_strings(archive)
            rels = _workbook_relationships(archive) if "xl/_rels/workbook.xml.rels" in names else {}
            workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
            sheets = []
            for index, sheet in enumerate(workbook_root.findall(f".//{{{XLSX_NS}}}sheet"), start=1):
                name = str(sheet.attrib.get("name") or f"Sheet{index}")
                rel_id = str(sheet.attrib.get(f"{{{REL_NS}}}id") or "")
                target = rels.get(rel_id) or f"xl/worksheets/sheet{index}.xml"
                if target not in names:
                    continue
                root = ET.fromstring(archive.read(target))
                sheets.append({"name": name, "path": target, "root": root})
            if not sheets:
                raise DocumentValidationError("XLSX workbook contains no readable worksheets.")
            self._sheets = sheets

    def sheet_names(self) -> list[str]:
        return [str(sheet["name"]) for sheet in self._sheets]

    def get_cell(self, sheet: object, row_index: int, column: object) -> str:
        cell = self._cell_element(sheet, row_index, column)
        return _xlsx_cell_text(cell, self._shared_strings) if cell is not None else ""

    def set_cell(self, sheet: object, row_index: int, column: object, value: object) -> None:
        sheet_record = self._sheet(sheet)
        root = sheet_record["root"]
        sheet_data = root.find(f"{{{XLSX_NS}}}sheetData")
        if sheet_data is None:
            sheet_data = ET.SubElement(root, f"{{{XLSX_NS}}}sheetData")
        row = _find_child_with_attr(sheet_data, "row", "r", str(row_index))
        if row is None:
            row = ET.Element(f"{{{XLSX_NS}}}row", {"r": str(row_index)})
            _insert_row_sorted(sheet_data, row)
        column_index = column_index_from_ref(column)
        cell_ref = f"{column_name(column_index)}{row_index}"
        cell = _find_child_with_attr(row, "c", "r", cell_ref)
        if cell is None:
            cell = ET.Element(f"{{{XLSX_NS}}}c", {"r": cell_ref})
            _insert_cell_sorted(row, cell)
        style = cell.attrib.get("s")
        cell.clear()
        cell.attrib["r"] = cell_ref
        if style:
            cell.attrib["s"] = style
        if isinstance(value, int | float) and not isinstance(value, bool):
            v = ET.SubElement(cell, f"{{{XLSX_NS}}}v")
            v.text = str(value)
        else:
            cell.attrib["t"] = "inlineStr"
            inline = ET.SubElement(cell, f"{{{XLSX_NS}}}is")
            text = ET.SubElement(inline, f"{{{XLSX_NS}}}t")
            text.text = str(value)

    def row_indices(self, sheet: object) -> list[int]:
        sheet_data = self._sheet(sheet)["root"].find(f"{{{XLSX_NS}}}sheetData")
        if sheet_data is None:
            return []
        values = []
        for row in sheet_data:
            if _local_name(row.tag) != "row":
                continue
            try:
                values.append(int(row.attrib.get("r") or "0"))
            except ValueError:
                continue
        return sorted(value for value in values if value > 0)

    def save(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        replacements = {
            str(sheet["path"]): ET.tostring(sheet["root"], encoding="utf-8", xml_declaration=True)
            for sheet in self._sheets
        }
        buffer = BytesIO()
        with ZipFile(self.path, "r") as source, ZipFile(buffer, "w", compression=ZIP_DEFLATED) as output:
            for info in source.infolist():
                payload = replacements.get(info.filename)
                output.writestr(info, payload if payload is not None else source.read(info.filename))
        target.write_bytes(buffer.getvalue())

    def _cell_element(self, sheet: object, row_index: int, column: object) -> ET.Element | None:
        sheet_data = self._sheet(sheet)["root"].find(f"{{{XLSX_NS}}}sheetData")
        if sheet_data is None:
            return None
        row = _find_child_with_attr(sheet_data, "row", "r", str(row_index))
        if row is None:
            return None
        cell_ref = f"{column_name(column_index_from_ref(column))}{row_index}"
        return _find_child_with_attr(row, "c", "r", cell_ref)

    def _sheet(self, selector: object) -> dict[str, Any]:
        if isinstance(selector, int):
            try:
                return self._sheets[selector]
            except IndexError as error:
                raise DocumentValidationError(f"Sheet index `{selector}` was not found.") from error
        text = str(selector or "0").strip()
        if text.isdigit():
            return self._sheet(int(text))
        for sheet in self._sheets:
            if str(sheet["name"]).casefold() == text.casefold():
                return sheet
        raise DocumentValidationError(f"Sheet `{text}` was not found.")


class DelimitedWorkbook(Workbook):
    def __init__(self, path: Path, *, delimiter: str) -> None:
        self.path = path
        self.delimiter = delimiter
        self.format = "tsv" if delimiter == "\t" else "csv"
        _ensure_file_budget(path)
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            self.rows = [[cell for cell in row] for row in csv.reader(handle, delimiter=delimiter)]

    def sheet_names(self) -> list[str]:
        return [self.path.stem or self.format.upper()]

    def get_cell(self, sheet: object, row_index: int, column: object) -> str:
        row_offset = row_index - 1
        column_offset = column_index_from_ref(column) - 1
        if row_offset < 0 or row_offset >= len(self.rows):
            return ""
        row = self.rows[row_offset]
        return str(row[column_offset]) if 0 <= column_offset < len(row) else ""

    def set_cell(self, sheet: object, row_index: int, column: object, value: object) -> None:
        row_offset = row_index - 1
        column_offset = column_index_from_ref(column) - 1
        while len(self.rows) <= row_offset:
            self.rows.append([])
        row = self.rows[row_offset]
        while len(row) <= column_offset:
            row.append("")
        row[column_offset] = str(value)

    def row_indices(self, sheet: object) -> list[int]:
        return list(range(1, len(self.rows) + 1))

    def save(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, delimiter=self.delimiter).writerows(self.rows)


def transform_spreadsheet(
    data_root: Path,
    uploaded_root: Path | None,
    generated_root: Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    target_workspace_path = _required_workspace_path(body.get("target_file"), "target_file")
    target_path = _resolve_generated_output(generated_root, target_workspace_path)
    source_refs = _source_refs(body.get("source_files"))
    base_workspace_path = str(body.get("base_file") or target_workspace_path)
    if target_workspace_path not in [item[1] for item in source_refs] and target_path.exists():
        source_refs.append(("target", target_workspace_path))
    if not source_refs:
        source_refs.append(("target", base_workspace_path))

    workbooks = _load_workbooks(uploaded_root, generated_root, source_refs)
    target_ref = _target_workbook_ref(workbooks, target_workspace_path, base_workspace_path)
    target_workbook = target_ref.workbook
    before_hash = _hash_file(target_path) if target_path.exists() else ""
    operations = _operations(body.get("operations"))
    audit_operations: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, operation in enumerate(operations, start=1):
        op_type = str(operation.get("type") or "").strip()
        if op_type == "lookup_and_copy":
            audit = _lookup_and_copy(index, operation, workbooks, target_ref)
        elif op_type == "write_cells":
            audit = _write_cells(index, operation, target_workbook)
        elif op_type == "find_values":
            audit = _find_values(index, operation, workbooks, target_ref)
        else:
            raise DocumentValidationError(f"Unsupported spreadsheet operation `{op_type}`.")
        audit_operations.append(audit)
        warnings.extend(str(item) for item in audit.get("warnings", []) if str(item))

    target_workbook.save(target_path)
    after_hash = _hash_file(target_path)
    report_path = _write_report(
        generated_root=generated_root,
        target_workspace_path=target_workspace_path,
        before_hash=before_hash,
        after_hash=after_hash,
        operations=audit_operations,
        warnings=warnings,
    )
    job = {
        "job_id": uuid4().hex,
        "title": str(body.get("title") or target_path.stem or "Spreadsheet transform"),
        "format": target_path.suffix.lower().lstrip(".") or target_workbook.format,
        "filename": target_path.name,
        "workspace_relative_path": workspace_relative_generated_path(target_path, generated_root.resolve()),
        "size_bytes": target_path.stat().st_size,
        "created_at": utc_now(),
        "metadata": {
            "kind": "spreadsheet_transform",
            "report_path": report_path,
            "operation_count": len(audit_operations),
        },
    }
    save_job(data_root, job)
    return {
        "status": "transformed",
        "document": job,
        "workspace_relative_path": job["workspace_relative_path"],
        "sha256_before": before_hash,
        "sha256_after": after_hash,
        "audit": {
            "source_files": _unique_source_paths(workbooks),
            "target_file": job["workspace_relative_path"],
            "operations": audit_operations,
            "warnings": warnings,
            "report_path": report_path,
        },
        "report_path": report_path,
    }


def _lookup_and_copy(
    index: int,
    operation: dict[str, Any],
    workbooks: dict[str, WorkbookRef],
    target_ref: WorkbookRef,
) -> dict[str, Any]:
    source_spec = _required_object(operation.get("source"), "source")
    target_spec = _required_object(operation.get("target"), "target")
    source = _workbook_for_spec(workbooks, source_spec, "source")
    target = _workbook_for_spec(workbooks, target_spec, "target", default=target_ref)
    source_sheet = source_spec.get("sheet", 0)
    target_sheet = target_spec.get("sheet", 0)
    source_key_column = source_spec.get("key_column") or "A"
    target_key_column = target_spec.get("key_column") or "A"
    source_columns = _columns(source_spec.get("columns"), "source.columns")
    target_columns = _columns(target_spec.get("columns"), "target.columns")
    if len(source_columns) != len(target_columns):
        raise DocumentValidationError("lookup_and_copy source.columns and target.columns must have the same length.")

    source_index = _row_index(source.workbook, source_sheet, source_key_column)
    target_index = _row_index(target.workbook, target_sheet, target_key_column)
    expected_keys = _expected_keys(operation.get("lookup"), workbooks, target_ref) or sorted(target_index)
    changes: list[dict[str, Any]] = []
    missing_source: list[str] = []
    missing_target: list[str] = []
    for key in expected_keys:
        source_row = source_index.get(key)
        target_row = target_index.get(key)
        if source_row is None:
            missing_source.append(key)
            continue
        if target_row is None:
            missing_target.append(key)
            continue
        for source_column, target_column in zip(source_columns, target_columns, strict=True):
            value = source.workbook.get_cell(source_sheet, source_row, source_column)
            before = target.workbook.get_cell(target_sheet, target_row, target_column)
            target.workbook.set_cell(target_sheet, target_row, target_column, value)
            changes.append(
                {
                    "key": key,
                    "sheet": _sheet_label(target.workbook, target_sheet),
                    "cell": f"{column_name(column_index_from_ref(target_column))}{target_row}",
                    "before": before,
                    "after": value,
                }
            )
    warnings = []
    if missing_source:
        warnings.append(f"{len(missing_source)} keys were missing in source `{source.alias}`.")
    if missing_target:
        warnings.append(f"{len(missing_target)} keys were missing in target `{target.alias}`.")
    return {
        "index": index,
        "type": "lookup_and_copy",
        "source": source.workspace_relative_path,
        "target": target.workspace_relative_path,
        "changed_cells": len(changes),
        "changes": changes,
        "missing_source_keys": missing_source,
        "missing_target_keys": missing_target,
        "warnings": warnings,
    }


def _write_cells(index: int, operation: dict[str, Any], target: Workbook) -> dict[str, Any]:
    sheet = operation.get("sheet", 0)
    writes = operation.get("cells")
    if not isinstance(writes, list) or not writes:
        raise DocumentValidationError("write_cells requires a non-empty cells array.")
    changes = []
    for item in writes:
        if not isinstance(item, dict):
            raise DocumentValidationError("write_cells cells must be objects.")
        row = _positive_int(item.get("row"), "row")
        column = item.get("column")
        if not column:
            raise DocumentValidationError("write_cells cell.column is required.")
        before = target.get_cell(sheet, row, column)
        value = item.get("value", "")
        target.set_cell(sheet, row, column, value)
        changes.append(
            {
                "sheet": _sheet_label(target, sheet),
                "cell": f"{column_name(column_index_from_ref(column))}{row}",
                "before": before,
                "after": str(value),
            }
        )
    return {"index": index, "type": "write_cells", "changed_cells": len(changes), "changes": changes, "warnings": []}


def _find_values(index: int, operation: dict[str, Any], workbooks: dict[str, WorkbookRef], target_ref: WorkbookRef) -> dict[str, Any]:
    spec = _required_object(operation.get("source") or operation, "source")
    workbook = _workbook_for_spec(workbooks, spec, "source", default=target_ref)
    sheet = spec.get("sheet", 0)
    column = spec.get("column") or spec.get("key_column") or "A"
    query = str(spec.get("value") or operation.get("value") or "")
    matches = []
    for row_index in workbook.workbook.row_indices(sheet):
        value = workbook.workbook.get_cell(sheet, row_index, column)
        if not query or value == query:
            matches.append({"row": row_index, "column": column_name(column_index_from_ref(column)), "value": value})
    return {
        "index": index,
        "type": "find_values",
        "source": workbook.workspace_relative_path,
        "matches": matches,
        "changed_cells": 0,
        "warnings": [],
    }


def _load_workbooks(uploaded_root: Path | None, generated_root: Path, refs: list[tuple[str, str]]) -> dict[str, WorkbookRef]:
    loaded: dict[str, WorkbookRef] = {}
    for position, (alias, workspace_relative_path) in enumerate(refs, start=1):
        path = resolve_workspace_file(uploaded_root, generated_root, workspace_relative_path)
        workbook = _load_workbook(path)
        keys = {alias, path.stem, path.name, workspace_relative_path, f"source_{position}"}
        for key in keys:
            if key:
                loaded[str(key)] = WorkbookRef(str(alias or path.stem), workspace_relative_path, path, workbook)
    return loaded


def _load_workbook(path: Path) -> Workbook:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return XlsxWorkbook(path)
    if suffix == ".csv":
        return DelimitedWorkbook(path, delimiter=",")
    if suffix == ".tsv":
        return DelimitedWorkbook(path, delimiter="\t")
    raise DocumentValidationError(f"Unsupported spreadsheet format `{suffix.lstrip('.')}`.")


def _target_workbook_ref(workbooks: dict[str, WorkbookRef], target_workspace_path: str, base_workspace_path: str) -> WorkbookRef:
    for key in (target_workspace_path, Path(target_workspace_path).name, Path(target_workspace_path).stem, "target", base_workspace_path):
        ref = workbooks.get(str(key))
        if ref is not None:
            return ref
    raise DocumentValidationError("target_file must exist or be listed in source_files/base_file.")


def _workbook_for_spec(
    workbooks: dict[str, WorkbookRef],
    spec: dict[str, Any],
    field: str,
    *,
    default: WorkbookRef | None = None,
) -> WorkbookRef:
    raw_key = spec.get("file") or spec.get("source") or spec.get("alias")
    if raw_key in (None, "") and default is not None:
        return default
    key = str(raw_key or "").strip()
    ref = workbooks.get(key)
    if ref is None:
        raise DocumentValidationError(f"{field}.file `{key}` was not found in source_files.")
    return ref


def _row_index(workbook: Workbook, sheet: object, key_column: object) -> dict[str, int]:
    result: dict[str, int] = {}
    for row_index in workbook.row_indices(sheet):
        key = workbook.get_cell(sheet, row_index, key_column).strip()
        if key and key not in result:
            result[key] = row_index
    return result


def _expected_keys(raw_lookup: object, workbooks: dict[str, WorkbookRef], target_ref: WorkbookRef) -> list[str]:
    if raw_lookup in (None, ""):
        return []
    if isinstance(raw_lookup, list):
        return [str(item).strip() for item in raw_lookup if str(item).strip()]
    lookup = _required_object(raw_lookup, "lookup")
    ref = _workbook_for_spec(workbooks, lookup, "lookup", default=target_ref)
    sheet = lookup.get("sheet", 0)
    key_column = lookup.get("key_column") or "A"
    return sorted(_row_index(ref.workbook, sheet, key_column))


def _write_report(
    *,
    generated_root: Path,
    target_workspace_path: str,
    before_hash: str,
    after_hash: str,
    operations: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    report_id = uuid4().hex
    report_path = generated_root / "document-generator" / "spreadsheet-reports" / f"{report_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Spreadsheet Transform Verification",
        "",
        f"- target: `{target_workspace_path}`",
        f"- sha256_before: `{before_hash}`",
        f"- sha256_after: `{after_hash}`",
        f"- operations: {len(operations)}",
        f"- warnings: {len(warnings)}",
        "",
        "## Operations",
    ]
    for operation in operations:
        lines.append(f"- {operation['index']}. {operation['type']}: {operation.get('changed_cells', 0)} changed cells")
        for warning in operation.get("warnings", []):
            lines.append(f"  - warning: {warning}")
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return workspace_relative_generated_path(report_path, generated_root.resolve())


def _source_refs(raw_value: object) -> list[tuple[str, str]]:
    if raw_value in (None, ""):
        return []
    if not isinstance(raw_value, list):
        raise DocumentValidationError("source_files must be an array.")
    refs: list[tuple[str, str]] = []
    for index, item in enumerate(raw_value, start=1):
        if isinstance(item, str):
            path = _required_workspace_path(item, "source_files")
            refs.append((Path(path).stem or f"source_{index}", path))
        elif isinstance(item, dict):
            path = _required_workspace_path(item.get("workspace_relative_path") or item.get("path"), "source_files.path")
            refs.append((str(item.get("alias") or Path(path).stem or f"source_{index}"), path))
        else:
            raise DocumentValidationError("source_files entries must be strings or objects.")
    return refs


def _unique_source_paths(workbooks: dict[str, WorkbookRef]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for ref in workbooks.values():
        if ref.workspace_relative_path in seen:
            continue
        seen.add(ref.workspace_relative_path)
        paths.append(ref.workspace_relative_path)
    return paths


def _operations(raw_value: object) -> list[dict[str, Any]]:
    if not isinstance(raw_value, list) or not raw_value:
        raise DocumentValidationError("operations must be a non-empty array.")
    operations = []
    for item in raw_value:
        if not isinstance(item, dict):
            raise DocumentValidationError("operations entries must be objects.")
        operations.append(item)
    return operations


def _columns(raw_value: object, field: str) -> list[object]:
    if not isinstance(raw_value, list) or not raw_value:
        raise DocumentValidationError(f"{field} must be a non-empty array.")
    return raw_value


def _resolve_generated_output(generated_root: Path, workspace_relative_path: str) -> Path:
    if not workspace_relative_path.startswith("storage/generated/"):
        raise DocumentValidationError("target_file must be under storage/generated/.")
    relative = Path(workspace_relative_path.removeprefix("storage/generated/"))
    if relative.is_absolute() or ".." in relative.parts or not relative.name:
        raise DocumentValidationError("target_file escapes generated storage.")
    root = generated_root.resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise DocumentValidationError("target_file escapes generated storage.")
    return target


def _required_workspace_path(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DocumentValidationError(f"{field} is required.")
    if not (text.startswith("storage/generated/") or text.startswith("storage/uploaded/")):
        raise DocumentValidationError(f"{field} must be under storage/generated or storage/uploaded.")
    return text


def _required_object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DocumentValidationError(f"{field} must be an object.")
    return value


def _positive_int(value: object, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise DocumentValidationError(f"{field} must be a positive integer.") from error
    if parsed <= 0:
        raise DocumentValidationError(f"{field} must be a positive integer.")
    return parsed


def _ensure_file_budget(path: Path) -> None:
    if path.stat().st_size > MAX_SPREADSHEET_BYTES:
        raise DocumentValidationError("Spreadsheet file is too large for transform.")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workbook_relationships(archive: ZipFile) -> dict[str, str]:
    root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rels = {}
    for rel in root:
        if _local_name(rel.tag) != "Relationship":
            continue
        rel_id = str(rel.attrib.get("Id") or "")
        target = str(rel.attrib.get("Target") or "")
        if not rel_id or not target:
            continue
        rels[rel_id] = target.lstrip("/") if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
    return rels


def _xlsx_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings = []
    for item in root:
        values = [(element.text or "") for element in item.iter() if _local_name(element.tag) == "t" and element.text]
        strings.append("".join(values))
    return strings


def _xlsx_cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(element.text or "" for element in cell.iter() if _local_name(element.tag) == "t")
    value = next((element.text or "" for element in cell if _local_name(element.tag) == "v"), "")
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return value
    return value


def column_index_from_ref(value: object) -> int:
    if isinstance(value, int):
        if value <= 0:
            raise DocumentValidationError("Column indexes are 1-based.")
        return value
    text = str(value or "").strip().upper()
    match = re.fullmatch(r"[A-Z]+", text)
    if not match:
        raise DocumentValidationError(f"Invalid spreadsheet column `{value}`.")
    index = 0
    for char in text:
        index = index * 26 + ord(char) - ord("A") + 1
    return index


def column_name(index: int) -> str:
    if index <= 0:
        raise DocumentValidationError("Column indexes are 1-based.")
    name = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def _find_child_with_attr(parent: ET.Element, local_name: str, attr_name: str, attr_value: str) -> ET.Element | None:
    for child in parent:
        if _local_name(child.tag) == local_name and child.attrib.get(attr_name) == attr_value:
            return child
    return None


def _insert_row_sorted(sheet_data: ET.Element, row: ET.Element) -> None:
    row_index = int(row.attrib["r"])
    for index, existing in enumerate(list(sheet_data)):
        if _local_name(existing.tag) != "row":
            continue
        try:
            if int(existing.attrib.get("r") or "0") > row_index:
                sheet_data.insert(index, row)
                return
        except ValueError:
            continue
    sheet_data.append(row)


def _insert_cell_sorted(row: ET.Element, cell: ET.Element) -> None:
    cell_column = column_index_from_ref(re.sub(r"\d+$", "", cell.attrib["r"]))
    for index, existing in enumerate(list(row)):
        if _local_name(existing.tag) != "c":
            continue
        existing_ref = re.sub(r"\d+$", "", existing.attrib.get("r") or "")
        if existing_ref and column_index_from_ref(existing_ref) > cell_column:
            row.insert(index, cell)
            return
    row.append(cell)


def _sheet_label(workbook: Workbook, selector: object) -> str:
    names = workbook.sheet_names()
    if isinstance(selector, int) and 0 <= selector < len(names):
        return names[selector]
    return str(selector)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
