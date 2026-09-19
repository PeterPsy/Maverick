"""Official external.static-bundle.export v1; no publishing or source-tree handoff."""
import base64
import hashlib
import io
from pathlib import Path
import re
import zipfile

from external_export_assets import ExportError, MAX_ZIP, collect_files, prepare_assets


def export_static_bundle(data_root: Path, body: dict):
    # Import only Website Studio-owned APIs. External Apps never imports these.
    from store import get_site, get_build, _site_mutation_lock, _source_version_for_site

    if body.get("schema_version") != "external-static-export-request.v1":
        raise ExportError("interface_version_unsupported")
    if body.get("entity_type") != "site":
        raise ExportError("source_not_exportable")
    if body.get("requested_format") not in {"static_bundle", "spa_bundle"}:
        raise ExportError("unsupported_format")
    release_id = body.get("release_id", "")
    if not isinstance(release_id, str) or not re.fullmatch(r"rel_[a-f0-9]{32}", release_id):
        raise ExportError("invalid_release_id")
    try:
        site = get_site(data_root, body.get("entity_id"))
    except ValueError as error:
        raise ExportError("source_not_found") from error
    with _site_mutation_lock(data_root, site["id"]):
        try:
            build = get_build(data_root, body.get("build_id"))
        except ValueError as error:
            raise ExportError("build_required") from error
        if build["site_id"] != site["id"] or build["status"] != "passed":
            raise ExportError("build_required")
        if build.get("runtime_kind") not in {"static_export", "node_build"}:
            raise ExportError("source_not_exportable")
        ref = build.get("artifact_ref", {})
        revision = ref.get("source_version")
        if not revision or revision != _source_version_for_site(get_site(data_root, site["id"])):
            raise ExportError("build_stale")
        if build["runtime_kind"] == "static_export":
            relative = ref.get("artifact_root", "")
        else:
            relative = ref.get("runtime_root", "")
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ExportError("source_not_exportable")
        candidate = data_root / relative
        allowed = data_root / "sites" / site["id"] / "builds" / build["id"]
        if not candidate.is_dir() or not candidate.resolve().is_relative_to(allowed.resolve()):
            raise ExportError("source_not_exportable")
        if build["runtime_kind"] == "node_build":
            # Preview metadata may point to the source index.html. Never export
            # that root: require one actual built web directory, without guessing
            # between ambiguous outputs or rebuilding during publication.
            docroot = ref.get("docroot", "")
            outputs = [name for name in ("dist", "build", "out", "public") if (candidate / name / "index.html").is_file()]
            if docroot in outputs:
                candidate /= docroot
            elif not docroot and len(outputs) == 1:
                candidate /= outputs[0]
            else:
                raise ExportError("source_not_exportable")
        if any(path.is_symlink() for path in (candidate, *candidate.parents)):
            raise ExportError("source_not_exportable")
        files = prepare_assets(collect_files(candidate), release_id)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name in sorted(files):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                # Stored entries avoid ambiguous decompression ratios, deterministic bytes.
                archive.writestr(info, files[name], compress_type=zipfile.ZIP_STORED)
                if stream.tell() > MAX_ZIP:
                    raise ExportError("artifact_too_large")
        data = stream.getvalue()
        if len(data) > MAX_ZIP:
            raise ExportError("artifact_too_large")
    return {"schema_version": "external-static-export.v1", "entity_type": "site", "entity_id": site["id"],
            "source_revision": revision, "release_id": release_id, "format": body["requested_format"],
            "entrypoint": "index.html", "artifact": {"transport": "base64", "content_base64": base64.b64encode(data).decode("ascii"),
            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}}
