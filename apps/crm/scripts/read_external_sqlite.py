"""Read an explicit SQLite export into a redacted adapter source on stdout.

This offline operator utility never executes an SQL dump, modifies the source,
opens production D1, or imports data. Feed its JSON to crm.import_plan first.
"""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from domains.import_sources import MAX_IMPORT_BYTES, MAX_IMPORT_ROWS, safe_source
from domains.versy_adapter import TABLE_TYPES


def read_source(path: Path, source_id: str):
    uri = path.resolve(strict=True).as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        available = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables, count = {}, 0
        for table in sorted(available & TABLE_TYPES.keys()):
            rows = [safe_source(dict(row)) for row in db.execute(f'SELECT * FROM "{table}" LIMIT ?', (MAX_IMPORT_ROWS + 1,))]
            count += len(rows)
            if count > MAX_IMPORT_ROWS:
                raise ValueError("Database exceeds the atomic batch limit; prepare ordered exports through the source system.")
            tables[table] = rows
        source = {"format": "versy", "source_id": source_id, "tables": tables}
        if len(json.dumps(source).encode()) > MAX_IMPORT_BYTES:
            raise ValueError("Database export exceeds 8 MB; prepare smaller ordered batches.")
        excluded = sorted(name for name in available - TABLE_TYPES.keys() if not name.startswith("sqlite_"))
        return source, excluded
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_file", type=Path)
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args()
    source, excluded = read_source(args.sqlite_file, args.source_id)
    if excluded:
        print("Not exported (configuration, cache or unsupported tables): " + ", ".join(excluded), file=sys.stderr)
    print(json.dumps(source, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
