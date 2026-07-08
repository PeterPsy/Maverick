#!/usr/bin/env python3
"""Collect repeatable startup baseline metrics from committed frontend assets."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import re
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST_ROOTS = {
    "base-shell": ROOT / "apps/base-shell/frontend/dist",
    "chat": ROOT / "apps/chat/frontend/dist",
}
MEASURED_SUFFIXES = {".css", ".js", ".woff", ".woff2"}
HASHED_ASSET_PATTERN = re.compile(r"-.{8,}\.[^.]+$")


def _gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=9))


def _file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".js":
        return "js"
    if suffix == ".css":
        return "css"
    if suffix in {".woff", ".woff2"}:
        return "font"
    return "other"


def _measured_files(app_id: str, root: Path) -> Iterable[dict[str, object]]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in MEASURED_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix()
        raw_bytes = path.stat().st_size
        gzip_bytes = _gzip_size(path)
        yield {
            "app_id": app_id,
            "path": relative,
            "kind": _file_kind(path),
            "raw_bytes": raw_bytes,
            "gzip_bytes": gzip_bytes,
            "gzip_ratio": round(gzip_bytes / raw_bytes, 4) if raw_bytes else 0,
            "hashed_asset": relative.startswith("assets/") and bool(HASHED_ASSET_PATTERN.search(path.name)),
        }


def collect_baseline() -> dict[str, object]:
    files: list[dict[str, object]] = []
    totals: dict[str, dict[str, object]] = {}
    html: dict[str, dict[str, object]] = {}
    for app_id, root in DEFAULT_DIST_ROOTS.items():
        app_files = list(_measured_files(app_id, root))
        files.extend(app_files)
        by_kind: dict[str, dict[str, int]] = {}
        for item in app_files:
            kind = str(item["kind"])
            bucket = by_kind.setdefault(kind, {"raw_bytes": 0, "gzip_bytes": 0, "file_count": 0})
            bucket["raw_bytes"] += int(item["raw_bytes"])
            bucket["gzip_bytes"] += int(item["gzip_bytes"])
            bucket["file_count"] += 1
        totals[app_id] = {
            "raw_bytes": sum(int(item["raw_bytes"]) for item in app_files),
            "gzip_bytes": sum(int(item["gzip_bytes"]) for item in app_files),
            "file_count": len(app_files),
            "by_kind": by_kind,
        }
        index_html = root / "index.html"
        html[app_id] = {
            "exists": index_html.exists(),
            "raw_bytes": index_html.stat().st_size if index_html.exists() else 0,
            "expected_cache_control": "no-store",
        }
    return {
        "metric_source": "committed frontend dist assets",
        "apps": sorted(DEFAULT_DIST_ROOTS),
        "totals": totals,
        "html": html,
        "files": files,
    }


def _print_text(payload: dict[str, object]) -> None:
    print("Maverick startup asset baseline")
    print("source: committed frontend dist assets")
    for app_id in payload["apps"]:
        total = payload["totals"][app_id]
        print(f"{app_id}: raw={total['raw_bytes']} gzip={total['gzip_bytes']} files={total['file_count']}")
        for kind, bucket in sorted(total["by_kind"].items()):
            print(f"  {kind}: raw={bucket['raw_bytes']} gzip={bucket['gzip_bytes']} files={bucket['file_count']}")
    print("largest files:")
    for item in sorted(payload["files"], key=lambda row: int(row["raw_bytes"]), reverse=True)[:12]:
        print(f"  {item['app_id']} {item['path']} raw={item['raw_bytes']} gzip={item['gzip_bytes']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()
    payload = collect_baseline()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
