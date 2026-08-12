"""Persistent cached builder for independently signed OpenDesign web overlays."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time
from typing import Any

from opendesign_archive import write_deterministic_archive
from opendesign_artifact import platform_key, sha256_file, write_canonical_json
from opendesign_attestation import cyclonedx_sbom, license_inventory, notice_text, package_inventory
from opendesign_build import build_environment, verify_toolchain
from opendesign_process import run_command
from opendesign_source import apply_patch_series, export_source
from opendesign_supply_chain import read_json
from opendesign_web_materialization import publish_web_overlay
from opendesign_web_overlay import VerifiedWebOverlay


CACHE_SCHEMA_VERSION = "1"


class WebBuildError(RuntimeError):
    """Raised when an incremental or release overlay build fails closed."""


@dataclass(frozen=True)
class WebCacheKeys:
    dependency: str
    source_build: str
    next: str
    lockfile: str
    package_graph: str
    toolchain: str


@dataclass(frozen=True)
class WebBuildMetrics:
    duration_seconds: float
    dependency_cache_hit: bool
    source_build_cache_hit: bool
    next_cache_hit: bool
    install_skipped: bool


@dataclass(frozen=True)
class WebBuildResult:
    overlay: VerifiedWebOverlay
    cache_hit: bool
    derivations: int
    reproducible: bool
    keys: WebCacheKeys
    metrics: tuple[WebBuildMetrics, ...]


def build_dev_overlay(
    repository: Path,
    *,
    manifest: dict[str, Any],
    service_root: Path,
    cache_root: Path,
    registry_root: Path,
    signing_key: Path,
    trust_contract: Path,
    work_parent: Path,
    runtime_session_id: str | None = None,
    compatible_runtime_artifact_sha256: frozenset[str] | None = None,
) -> WebBuildResult:
    with tempfile.TemporaryDirectory(prefix="od-web-dev-", dir=_real_directory(work_parent)) as temporary:
        derivation, keys, metrics = _derive_once(
            repository,
            Path(temporary) / "derive",
            manifest=manifest,
            service_root=service_root,
            cache_root=cache_root,
            signing_key=signing_key,
            runtime_session_id=runtime_session_id,
            allow_source_cache=True,
            allow_next_cache=True,
            compatible_runtime_artifact_sha256=compatible_runtime_artifact_sha256,
        )
        digest = sha256_file(derivation / "static.tar.gz")
        overlay, cache_hit = publish_web_overlay(
            derivation,
            registry_root=registry_root,
            expected_digest=digest,
            trust_contract=trust_contract,
        )
    return WebBuildResult(overlay, cache_hit, 1, False, keys, (metrics,))


def build_release_overlay(
    repository: Path,
    *,
    manifest: dict[str, Any],
    service_root: Path,
    cache_root: Path,
    registry_root: Path,
    signing_key: Path,
    trust_contract: Path,
    work_parent: Path,
    runtime_session_id: str | None = None,
    compatible_runtime_artifact_sha256: frozenset[str] | None = None,
) -> WebBuildResult:
    with tempfile.TemporaryDirectory(prefix="od-web-release-", dir=_real_directory(work_parent)) as temporary:
        root = Path(temporary)
        results = []
        keys: WebCacheKeys | None = None
        metrics: list[WebBuildMetrics] = []
        for sequence in (1, 2):
            derivation, observed_keys, observed_metrics = _derive_once(
                repository,
                root / f"derive-{sequence}",
                manifest=manifest,
                service_root=service_root,
                cache_root=cache_root,
                signing_key=signing_key,
                runtime_session_id=runtime_session_id,
                allow_source_cache=False,
                allow_next_cache=False,
                compatible_runtime_artifact_sha256=compatible_runtime_artifact_sha256,
            )
            keys = observed_keys if keys is None else keys
            if observed_keys != keys:
                raise WebBuildError("release derivations resolved different build inputs")
            results.append(derivation)
            metrics.append(observed_metrics)
        _assert_byte_reproducible(results[0], results[1])
        digest = sha256_file(results[0] / "static.tar.gz")
        overlay, cache_hit = publish_web_overlay(
            results[0],
            registry_root=registry_root,
            expected_digest=digest,
            trust_contract=trust_contract,
        )
    assert keys is not None
    return WebBuildResult(overlay, cache_hit, 2, True, keys, tuple(metrics))


def compute_web_cache_keys(
    source: Path,
    *,
    manifest: dict[str, Any],
    service_root: Path,
    node_version: str,
    pnpm_version: str,
) -> WebCacheKeys:
    lockfile = source / "pnpm-lock.yaml"
    lockfile_sha256 = sha256_file(lockfile)
    package_graph_sha256 = _package_graph_sha256(source)
    toolchain_payload = {
        "node": node_version,
        "pnpm": pnpm_version,
        "platform": platform_key(),
        "machine": platform.machine(),
    }
    toolchain_sha256 = _payload_sha256(toolchain_payload)
    dependency = _payload_sha256(
        {
            "lockfile_sha256": lockfile_sha256,
            "package_graph_sha256": package_graph_sha256,
            "toolchain_sha256": toolchain_sha256,
        }
    )
    series = read_json(service_root / manifest["fallback_build"]["patch_series"])
    web_patches = {
        str(entry["component"]): str(entry["sha256"])
        for entry in series["patches"]
        if entry.get("component") in {"web-build", "web-react"}
    }
    source_build = _payload_sha256(
        {
            "upstream_commit": manifest["upstream"]["commit"],
            "dependency": dependency,
            "web_patches": web_patches,
        }
    )
    next_key = _payload_sha256(
        {
            "dependency": dependency,
            "next_major": _next_major(source),
            "toolchain_sha256": toolchain_sha256,
        }
    )
    return WebCacheKeys(
        dependency,
        source_build,
        next_key,
        lockfile_sha256,
        package_graph_sha256,
        toolchain_sha256,
    )


def _derive_once(
    repository: Path,
    result_root: Path,
    *,
    manifest: dict[str, Any],
    service_root: Path,
    cache_root: Path,
    signing_key: Path,
    runtime_session_id: str | None,
    allow_source_cache: bool,
    allow_next_cache: bool,
    compatible_runtime_artifact_sha256: frozenset[str] | None,
) -> tuple[Path, WebCacheKeys, WebBuildMetrics]:
    started = time.monotonic()
    result_root.mkdir(parents=True)
    source = result_root / "source"
    logs = result_root / "logs"
    tool_bin = result_root / "tool-bin"
    tool_bin.mkdir()
    export_source(repository, source, manifest)
    patch_evidence = apply_patch_series(
        source,
        service_root,
        manifest,
        components={"web-build", "web-react"},
    )
    run_command([*manifest["toolchain"]["corepack_enable"], str(tool_bin)], cwd=source)
    environment = build_environment(
        result_root,
        tool_bin=tool_bin,
        manifest=manifest,
        pnpm_store=_real_cache_directory(cache_root) / "pnpm-store",
    )
    verify_toolchain(source, manifest, env=environment)
    node_version = run_command(["node", "--version"], cwd=source, env=environment, capture=True).stdout
    pnpm_version = run_command(
        ["corepack", "pnpm", "--version"],
        cwd=source,
        env=environment,
        capture=True,
    ).stdout
    keys = compute_web_cache_keys(
        source,
        manifest=manifest,
        service_root=service_root,
        node_version=node_version,
        pnpm_version=pnpm_version,
    )
    cache = _real_cache_directory(cache_root)
    dependency_root = cache / "dependencies" / keys.dependency
    source_root = cache / "source-build" / keys.source_build
    next_root = cache / "next" / keys.next

    dependency_hit = _restore_dependency_cache(source, dependency_root, keys)
    if not dependency_hit:
        build = manifest["fallback_build"]["build"]
        run_command(
            build["install"],
            cwd=source,
            env={**environment, **build["install_environment"]},
            log_path=logs / "install.log",
            heavy=True,
            runtime_session_id=runtime_session_id,
        )
        if sha256_file(source / "pnpm-lock.yaml") != keys.lockfile:
            raise WebBuildError("OpenDesign web install modified pnpm-lock.yaml")
        _write_dependency_cache(source, dependency_root, keys)

    static_output = result_root / "static"
    source_hit = allow_source_cache and _restore_source_cache(source_root, static_output, keys)
    next_hit = False
    if not source_hit:
        if allow_next_cache:
            next_hit = _restore_next_cache(source, next_root, keys)
        command = _web_build_command(manifest)
        run_command(
            command,
            cwd=source,
            env={**environment, **manifest["fallback_build"]["build"]["compile_environment"]},
            log_path=logs / "web-build.log",
            heavy=True,
            runtime_session_id=runtime_session_id,
        )
        if sha256_file(source / "pnpm-lock.yaml") != keys.lockfile:
            raise WebBuildError("OpenDesign web build modified pnpm-lock.yaml")
        built = _real_directory(source / manifest["web_patch"]["source_output_path"])
        for source_map in built.rglob("*.map"):
            source_map.unlink()
        shutil.copytree(built, static_output)
        if allow_next_cache:
            _write_next_cache(source, next_root, keys)
        if allow_source_cache:
            _write_source_cache(static_output, source_root, keys)

    overlay_root = result_root / "overlay"
    _assemble_overlay(
        overlay_root,
        static_output=static_output,
        source=source,
        manifest=manifest,
        keys=keys,
        patch_evidence=patch_evidence,
        signing_key=signing_key,
        node_version=node_version,
        pnpm_version=pnpm_version,
        compatible_runtime_artifact_sha256=compatible_runtime_artifact_sha256,
    )
    metrics = WebBuildMetrics(
        round(time.monotonic() - started, 6),
        dependency_hit,
        source_hit,
        next_hit,
        dependency_hit,
    )
    return overlay_root, keys, metrics


def _assemble_overlay(
    root: Path,
    *,
    static_output: Path,
    source: Path,
    manifest: dict[str, Any],
    keys: WebCacheKeys,
    patch_evidence: list[dict[str, Any]],
    signing_key: Path,
    node_version: str,
    pnpm_version: str,
    compatible_runtime_artifact_sha256: frozenset[str] | None,
) -> None:
    root.mkdir()
    static = root / "static"
    shutil.copytree(static_output, static)
    files = {
        "schema_version": "1",
        "files": [
            {
                "path": path.relative_to(static).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(static.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ],
    }
    write_canonical_json(root / "files.json", files)
    write_deterministic_archive(static, root / "static.tar.gz")
    overlay_digest = sha256_file(root / "static.tar.gz")

    packages = package_inventory(source)
    licenses = license_inventory(packages, upstream=manifest["upstream"])
    write_canonical_json(
        root / "sbom.cdx.json",
        cyclonedx_sbom(packages, version=manifest["upstream"]["release_version"]),
    )
    write_canonical_json(root / "licenses.json", licenses)
    (root / "NOTICE").write_text(notice_text(licenses), encoding="utf-8")
    write_canonical_json(
        root / "provenance.json",
        {
            "schema_version": "1",
            "subject": {"web_overlay_sha256": overlay_digest},
            "upstream": {
                "commit": manifest["upstream"]["commit"],
                "version": manifest["upstream"]["release_version"],
            },
            "inputs": asdict(keys),
            "patches": patch_evidence,
            "reproducible_environment": manifest["fallback_build"]["build"]["environment"],
        },
    )
    descriptors = {
        name: _file_descriptor(root / path, path)
        for name, path in {
            "static_archive": "static.tar.gz",
            "file_manifest": "files.json",
            "sbom": "sbom.cdx.json",
            "licenses": "licenses.json",
            "notice": "NOTICE",
            "provenance": "provenance.json",
        }.items()
    }
    series = read_json(Path(__file__).resolve().parent / manifest["fallback_build"]["patch_series"])
    patch_digest = {entry["component"]: entry["sha256"] for entry in series["patches"]}
    runtime_digest = manifest["artifact"]["assets"][platform_key()]["sha256"]
    compatible_runtime_digests = sorted(
        compatible_runtime_artifact_sha256 or frozenset({runtime_digest})
    )
    if runtime_digest not in compatible_runtime_digests:
        raise WebBuildError("web overlay compatibility must include the selected runtime artifact")
    overlay_manifest = {
        "schema_version": "1",
        "web_overlay_sha256": overlay_digest,
        **descriptors,
        "compatibility": {
            "runtime_artifact_sha256": compatible_runtime_digests,
            "od_version": manifest["upstream"]["release_version"],
            "upstream_commit": manifest["upstream"]["commit"],
            "platform": manifest["distribution"]["platform"],
        },
        "inputs": {
            "lockfile_sha256": keys.lockfile,
            "package_graph_sha256": keys.package_graph,
            "web_build_patch_sha256": patch_digest["web-build"],
            "web_react_patch_sha256": patch_digest["web-react"],
            "node": node_version,
            "pnpm": pnpm_version,
            "toolchain_sha256": keys.toolchain,
        },
        "signature": {"algorithm": "Ed25519", "path": "manifest.sig"},
    }
    write_canonical_json(root / "manifest.json", overlay_manifest)
    _sign_manifest(root / "manifest.json", signing_key, root / "manifest.sig")


def _restore_dependency_cache(source: Path, root: Path, keys: WebCacheKeys) -> bool:
    if not _valid_cache_marker(root, "dependency", keys.dependency):
        return False
    inventory = read_json(root / "node-modules.json")
    paths = inventory.get("paths")
    if not isinstance(paths, list) or not paths:
        return False
    for relative in paths:
        if not isinstance(relative, str) or ".." in Path(relative).parts:
            return False
        cached = root / "payload" / relative
        if not cached.is_dir() or cached.is_symlink():
            return False
    for relative in paths:
        destination = source / str(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree_cached(root / "payload" / str(relative), destination)
    return True


def _write_dependency_cache(source: Path, root: Path, keys: WebCacheKeys) -> None:
    paths = _dependency_cache_paths(source)
    if not paths:
        raise WebBuildError("dependency install produced no node_modules cache inputs")
    _replace_cache_root(root)
    payload = root / "payload"
    for relative in paths:
        destination = payload / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_tree_cached(source / relative, destination)
    write_canonical_json(root / "node-modules.json", {"schema_version": "1", "paths": paths})
    _write_cache_marker(root, "dependency", keys.dependency)


def _dependency_cache_paths(source: Path) -> list[str]:
    return sorted(
        path.relative_to(source).as_posix()
        for path in source.rglob("node_modules")
        if path.is_dir()
        and not path.is_symlink()
        and path.relative_to(source).parts.count("node_modules") == 1
    )


def _restore_source_cache(root: Path, destination: Path, keys: WebCacheKeys) -> bool:
    if not _valid_cache_marker(root, "source-build", keys.source_build):
        return False
    static = root / "static"
    if not static.is_dir() or static.is_symlink():
        return False
    _copy_tree_cached(static, destination)
    return True


def _write_source_cache(static: Path, root: Path, keys: WebCacheKeys) -> None:
    _replace_cache_root(root)
    _copy_tree_cached(static, root / "static")
    _write_cache_marker(root, "source-build", keys.source_build)


def _restore_next_cache(source: Path, root: Path, keys: WebCacheKeys) -> bool:
    if not _valid_cache_marker(root, "next", keys.next):
        return False
    cached = root / "cache"
    if not cached.is_dir() or cached.is_symlink():
        return False
    destination = source / "apps/web/.next/cache"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree_cached(cached, destination)
    return True


def _write_next_cache(source: Path, root: Path, keys: WebCacheKeys) -> None:
    cache = source / "apps/web/.next/cache"
    if not cache.is_dir() or cache.is_symlink():
        return
    _replace_cache_root(root)
    _copy_tree_cached(cache, root / "cache")
    _write_cache_marker(root, "next", keys.next)


def _replace_cache_root(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.is_symlink():
        raise WebBuildError("OpenDesign web cache path must not be a symlink")
    path.mkdir(parents=True)


def _copy_tree_cached(source: Path, destination: Path) -> None:
    """Copy a cache tree using CoW reflinks when supported, retaining a safe fallback."""
    if source.is_symlink() or not source.is_dir() or destination.exists() or destination.is_symlink():
        raise WebBuildError("OpenDesign cache copy endpoints are unsafe")
    destination.mkdir(parents=True)
    completed = subprocess.run(
        ["cp", "-a", "--reflink=auto", f"{source}/.", str(destination)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        shutil.rmtree(destination)
        raise WebBuildError("OpenDesign cache tree copy failed")


def _valid_cache_marker(root: Path, kind: str, key: str) -> bool:
    marker = root / "complete.json"
    if root.is_symlink() or not root.is_dir() or marker.is_symlink() or not marker.is_file():
        return False
    try:
        value = read_json(marker)
    except Exception:
        return False
    return value == {"schema_version": CACHE_SCHEMA_VERSION, "kind": kind, "key": key}


def _write_cache_marker(root: Path, kind: str, key: str) -> None:
    write_canonical_json(
        root / "complete.json",
        {"schema_version": CACHE_SCHEMA_VERSION, "kind": kind, "key": key},
    )


def _assert_byte_reproducible(first: Path, second: Path) -> None:
    first_paths = sorted(path.relative_to(first).as_posix() for path in first.rglob("*") if path.is_file())
    second_paths = sorted(path.relative_to(second).as_posix() for path in second.rglob("*") if path.is_file())
    if first_paths != second_paths:
        raise WebBuildError("release web derivations produced different file sets")
    for relative in first_paths:
        if (first / relative).read_bytes() != (second / relative).read_bytes():
            raise WebBuildError(f"release web derivations differ byte-for-byte: {relative}")


def _web_build_command(manifest: dict[str, Any]) -> list[str]:
    command = manifest.get("web_patch", {}).get("build_command")
    if (
        not isinstance(command, list)
        or command
        != [
            "corepack",
            "pnpm",
            "--filter",
            "@open-design/web...",
            "--workspace-concurrency=4",
            "--if-present",
            "run",
            "build",
        ]
    ):
        raise WebBuildError("OpenDesign web build command is missing or ambiguous")
    return list(command)


def _package_graph_sha256(source: Path) -> str:
    candidates = [source / "pnpm-workspace.yaml", source / "package.json"]
    candidates.extend(
        path for path in source.rglob("package.json") if "node_modules" not in path.parts
    )
    entries = [
        {"path": path.relative_to(source).as_posix(), "sha256": sha256_file(path)}
        for path in sorted(set(candidates))
        if path.is_file() and not path.is_symlink()
    ]
    return _payload_sha256(entries)


def _next_major(source: Path) -> str:
    package = read_json(source / "apps/web/package.json")
    dependencies = package.get("dependencies")
    value = dependencies.get("next") if isinstance(dependencies, dict) else None
    if not isinstance(value, str) or not value:
        raise WebBuildError("OpenDesign web Next version is not declared")
    match = next((part for part in value.replace("~", "").replace("^", "").split(".") if part.isdigit()), None)
    if match is None:
        raise WebBuildError("OpenDesign web Next major version is invalid")
    return match


def _payload_sha256(payload: object) -> str:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_descriptor(path: Path, relative: str) -> dict[str, object]:
    return {"path": relative, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def _sign_manifest(manifest: Path, signing_key: Path, signature: Path) -> None:
    completed = subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-rawin",
            "-inkey",
            str(_real_file(signing_key)),
            "-in",
            str(manifest),
            "-out",
            str(signature),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise WebBuildError("OpenDesign web overlay signature creation failed")


def _real_cache_directory(path: Path) -> Path:
    path = Path(path)
    if path.exists() or path.is_symlink():
        return _real_directory(path)
    path.mkdir(parents=True)
    return _real_directory(path)


def _real_directory(path: Path) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise WebBuildError("OpenDesign web builder requires a real directory")
    return path.resolve(strict=True)


def _real_file(path: Path) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise WebBuildError("OpenDesign web builder requires a real signing key")
    return path.resolve(strict=True)
