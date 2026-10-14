#!/usr/bin/env python3
"""Export the selected product apps using the official SDK package format."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.app_sdk.packaging import package_app_source
from core.apps.builtin_apps import discover_builtin_apps
from core.apps.contracts import parse_app_contract_file

DEFAULT_CATALOG_URL = "https://loopino.giuntitrail.com/catalog"


def export_catalog(repository_root: Path, output_root: Path, *, base_url: str = DEFAULT_CATALOG_URL) -> dict:
    """Write revalidated catalog JSON and immutable SDK bundles; never export tenant data."""
    repository_root = repository_root.resolve(strict=True)
    designated = repository_root / "installation/catalog"
    if output_root != designated or any(p.is_symlink() for p in (output_root, *output_root.parents)):
        raise ValueError("Catalog output must use the designated installation/catalog directory without symlinks")
    parsed_url = urlparse(base_url)
    if (parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username
            or parsed_url.password or parsed_url.query or parsed_url.fragment):
        raise ValueError("Catalog base URL must be an absolute HTTPS origin and optional path")
    if not (repository_root / "apps/bootstrap.json").is_file():
        raise ValueError("Product catalog export requires an explicit app bootstrap selection")
    output_root.mkdir(parents=True, exist_ok=True)
    artifact_root = output_root / "artifacts"
    artifact_root.mkdir(exist_ok=True)
    if artifact_root.is_symlink():
        raise ValueError("Catalog artifacts must use a real directory")
    items = []
    for spec in discover_builtin_apps(start_path=repository_root):
        parsed = parse_app_contract_file(spec.source_path)
        contract = json.loads((spec.source_path / "app_contract.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=output_root, prefix=".package-") as folder:
            result = package_app_source(spec.source_path, output_path=Path(folder) / "app.tar.gz")
            filename = f"{parsed.app_id}-{parsed.version}-{result.checksum_sha256}.tar.gz"
            destination = artifact_root / filename
            if destination.is_symlink():
                raise ValueError("Catalog artifact path must not be a symlink")
            Path(result.artifact_path).replace(destination)
            manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
            manifest["artifact"] = filename
            (artifact_root / (filename + ".manifest.json")).write_text(json.dumps(manifest, indent=2) + "\n")
        entrypoints = contract.get("entrypoints", {})
        surfaces = [name for name in ("frontend", "backend", "cli", "mcp") if entrypoints.get(name)]
        metadata = {key: contract[key] for key in ("distribution", "presentation", "visibility") if key in contract}
        version = {
            "app_id": parsed.app_id, "name": parsed.name, "version": parsed.version,
            "description": parsed.description, "publisher": parsed.publisher,
            "status": "published", "sha256": result.checksum_sha256,
            "artifact_download_url": base_url.rstrip("/") + "/artifacts/" + filename,
            "surfaces": surfaces, **metadata,
        }
        items.append({"app_id": parsed.app_id, "name": parsed.name,
                      "description": parsed.description, "publisher": parsed.publisher,
                      "latest_version": parsed.version, "surfaces": surfaces,
                      "versions": [version], **metadata})
    catalog = {"items": items, "count": len(items)}
    api = output_root / "api"
    if api.is_symlink():
        raise ValueError("Catalog API directory must not be a symlink")
    api.mkdir(exist_ok=True)
    target = api / "apps"
    if target.is_symlink():
        raise ValueError("Catalog index must not be a symlink")
    temporary = api / ".apps.new"
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(catalog, indent=2) + "\n")
    temporary.replace(target)
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_CATALOG_URL)
    args = parser.parse_args()
    catalog = export_catalog(ROOT, ROOT / "installation/catalog", base_url=args.base_url)
    print(json.dumps({"catalog": str(ROOT / "installation/catalog/api/apps"), "count": catalog["count"]}))


if __name__ == "__main__":
    main()
