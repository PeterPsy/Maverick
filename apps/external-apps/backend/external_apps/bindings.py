"""The public binding file is the ONLY active-release authority."""
import json
from pathlib import Path

from .errors import AppError
from .files import atomic_write, encoded, read_regular
from .policy import digest, identifier


def empty_binding(public_id):
    return {"public_id": public_id, "generation": 0, "enabled": False, "archived": False,
            "current": None, "previous": None, "operation_id": "", "hostname": ""}


def validate_binding(value, public_id):
    if not isinstance(value, dict) or value.get("public_id") != public_id:
        raise AppError("corrupt_binding", 503)
    if type(value.get("generation")) is not int or value["generation"] < 1:
        raise AppError("corrupt_binding", 503)
    if type(value.get("enabled")) is not bool or type(value.get("archived")) is not bool:
        raise AppError("corrupt_binding", 503)
    for name in ("current", "previous"):
        release = value.get(name)
        if release is not None:
            if not isinstance(release, dict):
                raise AppError("corrupt_binding", 503)
            identifier(release.get("release_id"), "rel_")
            digest(release.get("digest"))
            digest(release.get("manifest_digest"))
            if release.get("format") not in {"static_bundle", "spa_bundle"}:
                raise AppError("corrupt_binding", 503)
    if value["enabled"] and (not value.get("current") or value["archived"]):
        raise AppError("corrupt_binding", 503)
    return value


def read_binding(public_root: Path, public_id):
    identifier(public_id)
    path = public_root / "bindings" / f"{public_id}.json"
    try:
        return validate_binding(json.loads(read_regular(path, 8192)), public_id)
    except FileNotFoundError:
        return empty_binding(public_id)
    except (ValueError, KeyError, TypeError) as error:
        raise AppError("corrupt_binding", 503) from error


def write_binding(root, public_id, value, *, expected_generation):
    # Caller serializes read/CAS/write with publication_lock across processes.
    actual = read_binding(root / "public", public_id)
    if actual["generation"] != expected_generation:
        raise AppError("binding_changed", 409)
    if value.get("generation") != expected_generation + 1:
        raise AppError("invalid_generation", 409)
    validate_binding(value, public_id)
    atomic_write(root / "public/bindings" / f"{public_id}.json", encoded(value))
