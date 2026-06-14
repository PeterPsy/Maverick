"""Bounded preview runtime adapters for Website Studio."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import os
import posixpath
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from safety import copy_tree_snapshot, runtime_diagnostic_html, safe_relative_path


MAX_LOG_CHARS = 12000
BUILD_TIMEOUT_SECONDS = 180
COMMAND_TIMEOUT_SECONDS = 60
PHP_STARTUP_TIMEOUT_SECONDS = 5
PHP_REQUEST_TIMEOUT_SECONDS = 8
PHP_SERVER_TTL_SECONDS = 180
BUILD_CPU_LIMIT_SECONDS = 240
COMMAND_CPU_LIMIT_SECONDS = 90
PHP_CPU_LIMIT_SECONDS = 90
BUILD_MEMORY_LIMIT_BYTES = 1536 * 1024 * 1024
COMMAND_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
PHP_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
MAX_RUNTIME_OPEN_FILES = 256
MAX_RUNTIME_PROCESSES = 64
MAX_RENDER_BYTES = 2 * 1024 * 1024
MAX_RENDERED_ROUTES = 40
ALLOWED_WORKSPACE_BUILD_BINARIES = {
    "astro",
    "cssnano",
    "gatsby",
    "next",
    "postcss",
    "sass",
    "vite",
    "webpack",
}
UNSUPPORTED_WORKSPACE_BUILD_BINARIES = {
    "node-sass": "node-sass requires npm install scripts/native bindings and is not supported by the Website Studio preview runtime; use Dart Sass `sass` instead",
}
HTACCESS_RUNTIME_WARNING = ".htaccess rules are not fully reproduced by the Website Studio preview runtime"
PHP_SERVICES_RUNTIME_WARNING = "database, SMTP, analytics, payment, and third-party services require explicit preview configuration"
GLOBAL_RUNTIME_WARNINGS = frozenset({HTACCESS_RUNTIME_WARNING, PHP_SERVICES_RUNTIME_WARNING})


def runtime_process_policy() -> dict[str, object]:
    """Return the bounded subprocess policy used by Phase 3A previews."""
    return {
        "schema": "website-studio.runtime-process-policy.v1",
        "process_group_cleanup": os.name == "posix",
        "posix_resource_limits_best_effort": _resource_limits_available(),
        "safe_environment": [
            "CI",
            "HOME",
            "LANG",
            "LC_ALL",
            "NO_COLOR",
            "NPM_CONFIG_AUDIT",
            "NPM_CONFIG_FUND",
            "NPM_CONFIG_IGNORE_SCRIPTS",
            "NPM_CONFIG_UPDATE_NOTIFIER",
            "PATH",
            "TMPDIR",
            "WEBSITE_STUDIO_RUNTIME_POLICY",
        ],
        "timeouts_seconds": {
            "npm_install": BUILD_TIMEOUT_SECONDS,
            "build_command": COMMAND_TIMEOUT_SECONDS,
            "php_preview_startup": PHP_STARTUP_TIMEOUT_SECONDS,
            "php_preview_request": PHP_REQUEST_TIMEOUT_SECONDS,
            "php_preview_ttl": PHP_SERVER_TTL_SECONDS,
        },
        "resource_limits": {
            "npm_install": {
                "cpu_seconds": BUILD_CPU_LIMIT_SECONDS,
                "memory_bytes": BUILD_MEMORY_LIMIT_BYTES,
                "open_files": MAX_RUNTIME_OPEN_FILES,
                "processes": MAX_RUNTIME_PROCESSES,
            },
            "build_command": {
                "cpu_seconds": COMMAND_CPU_LIMIT_SECONDS,
                "memory_bytes": COMMAND_MEMORY_LIMIT_BYTES,
                "open_files": MAX_RUNTIME_OPEN_FILES,
                "processes": MAX_RUNTIME_PROCESSES,
            },
            "php_preview_server": {
                "cpu_seconds": PHP_CPU_LIMIT_SECONDS,
                "memory_bytes": PHP_MEMORY_LIMIT_BYTES,
                "open_files": MAX_RUNTIME_OPEN_FILES,
                "processes": MAX_RUNTIME_PROCESSES,
            },
        },
        "known_platform_gap": "OS-level sandboxing/network namespaces remain a generic platform hosting concern outside Website Studio Phase 1-3A.",
    }


def _resource_limits_available() -> bool:
    if os.name != "posix":
        return False
    try:
        import resource  # noqa: PLC0415
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class BuildPlan:
    package_manager: str
    commands: list[list[str]]
    warnings: list[str]
    missing_requirements: list[str]


@dataclass
class PhpPreviewServer:
    key: str
    port: int
    pid: int
    process: subprocess.Popen | None
    runtime_root: Path
    docroot: Path
    router: Path | None
    last_used: float
    process_group_id: int | None = None


_PHP_PREVIEW_SERVERS: dict[str, PhpPreviewServer] = {}
_PHP_PREVIEW_SERVERS_LOCK = threading.Lock()


def build_plan_for_source(source_root: Path) -> BuildPlan:
    package_json = _read_package_json(source_root)
    if not package_json:
        return BuildPlan("", [], [], ["package.json is required for a runtime asset build"])
    scripts = package_json.get("scripts") if isinstance(package_json.get("scripts"), dict) else {}
    package_manager = _detect_package_manager(source_root)
    missing: list[str] = []
    warnings: list[str] = []
    if package_manager != "npm":
        missing.append("only npm lockfile builds are enabled for Website Studio Phase 3A")
    elif not (source_root / "package-lock.json").exists():
        missing.append("npm package-lock.json is required for dependency installation")
    try:
        commands = _expand_script("build", scripts, stack=[])
    except ValueError as error:
        return BuildPlan(package_manager, [], warnings, [str(error)])
    return BuildPlan(package_manager, commands, warnings, missing)


def prepare_runtime_build(
    data_root: Path,
    site_id: str,
    source_root: Path,
    *,
    build_id: str,
    source_profile: dict[str, object],
) -> dict[str, object]:
    runtime_kind = str(source_profile.get("preview_runtime_kind") or "unavailable")
    if runtime_kind not in {"php", "node_build"}:
        return {
            "status": "skipped",
            "runtime_kind": runtime_kind,
            "warnings": [],
            "missing_requirements": [],
            "logs_summary": "No runtime build is needed for this source.",
            "artifact_ref": {},
        }

    needs_node_build = runtime_kind == "node_build" or bool(source_profile.get("has_package_manifest"))
    plan = build_plan_for_source(source_root) if needs_node_build else BuildPlan("", [], [], [])
    warnings = list(plan.warnings)
    missing = list(plan.missing_requirements)
    php_missing = _php_missing_requirement(runtime_kind)
    if php_missing:
        missing.append(php_missing)
    if needs_node_build and not plan.commands:
        missing.append("package.json does not expose an allowlisted build script")
    if missing:
        return {
            "status": "blocked",
            "runtime_kind": runtime_kind,
            "warnings": warnings,
            "missing_requirements": _dedupe(missing),
            "logs_summary": "Runtime build blocked before execution: " + "; ".join(_dedupe(missing)[:4]),
            "artifact_ref": {},
        }

    temp_root = data_root / ".tmp" / f"runtime_build_{build_id}"
    build_source = temp_root / "source"
    artifact_root = data_root / "sites" / site_id / "builds" / build_id / "runtime"
    try:
        copy_tree_snapshot(source_root, build_source)
        command_logs: list[str] = []
        if needs_node_build:
            install_result = _run_npm_install(build_source)
            command_logs.append(install_result)
            for command in plan.commands:
                command_logs.append(_run_allowlisted_command(build_source, command))
        else:
            command_logs.append("No Node asset build declared; PHP runtime artifact copied without dependency installation.")
        if artifact_root.exists():
            shutil.rmtree(artifact_root)
        artifact_root.parent.mkdir(parents=True, exist_ok=True)
        _copy_runtime_artifact(build_source, artifact_root)
        logs_summary = _bounded_log("\n".join(command_logs))
        return {
            "status": "passed",
            "runtime_kind": runtime_kind,
            "warnings": warnings,
            "missing_requirements": [],
            "logs_summary": logs_summary or "Runtime artifact prepared.",
            "artifact_ref": {
                "provider": "website-studio",
                "kind": "runtime_preview_artifact",
                "build_id": build_id,
                "runtime_root": artifact_root.relative_to(data_root).as_posix(),
                "docroot": str(source_profile.get("php_docroot") or ""),
                "runtime_kind": runtime_kind,
                "platform_surface": "website_studio_preview_runtime",
                "isolation": "opaque_origin_iframe",
            },
        }
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return {
            "status": "failed",
            "runtime_kind": runtime_kind,
            "warnings": warnings,
            "missing_requirements": [],
            "logs_summary": _bounded_log(str(error)),
            "artifact_ref": {},
        }
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)


def render_runtime_preview(
    data_root: Path,
    source_root: Path,
    *,
    route: str,
    source_profile: dict[str, object],
    artifact_ref: dict[str, object] | None = None,
) -> dict[str, object]:
    runtime_kind = str(source_profile.get("preview_runtime_kind") or "unavailable")
    if runtime_kind == "php":
        return _render_php_preview(data_root, source_root, route=route, source_profile=source_profile, artifact_ref=artifact_ref or {})
    if runtime_kind == "node_build":
        return _render_node_build_preview(data_root, source_root, route=route, source_profile=source_profile, artifact_ref=artifact_ref or {})
    return {
        "status": "blocked",
        "runtime_kind": runtime_kind,
        "html": runtime_diagnostic_html("Preview runtime unavailable", ["unsupported runtime kind"]),
        "title": "",
        "source_files": [],
        "warnings": [],
        "missing_requirements": ["unsupported runtime kind"],
        "http_status": 0,
    }


def runtime_capability_status(source_root: Path, source_profile: dict[str, object]) -> dict[str, object]:
    runtime_kind = str(source_profile.get("preview_runtime_kind") or "unavailable")
    missing = [str(item) for item in source_profile.get("missing_requirements", []) if str(item).strip()] if isinstance(source_profile.get("missing_requirements"), list) else []
    if runtime_kind == "php":
        php_missing = _php_missing_requirement(runtime_kind)
        if php_missing:
            missing.append(php_missing)
    if runtime_kind in {"php", "node_build"} and source_profile.get("has_package_manifest"):
        plan = build_plan_for_source(source_root)
        missing.extend(plan.missing_requirements)
        if not plan.commands:
            missing.append("package.json does not expose an allowlisted build script")
    status = "ready" if runtime_kind in {"php", "node_build"} and not _dedupe(missing) else str(source_profile.get("runtime_preview_status") or "blocked")
    return {
        "runtime_kind": runtime_kind,
        "runtime_status": status,
        "missing_requirements": _dedupe(missing),
    }


def source_files_for_runtime_route(source_root: Path, source_profile: dict[str, object]) -> list[str]:
    files: list[str] = []
    docroot = str(source_profile.get("php_docroot") or "").strip()
    if docroot and docroot != ".":
        for candidate in ("index.php", "index.html"):
            path = source_root / docroot / candidate
            if path.exists():
                files.append(f"{docroot}/{candidate}")
    else:
        for candidate in ("index.php", "index.html"):
            path = source_root / candidate
            if path.exists():
                files.append(candidate)
    for candidate in ("local/router.php", ".htaccess", "package.json", "webpack.config.js"):
        if (source_root / candidate).exists():
            files.append(candidate)
    return files


def runtime_environment_warnings(source_root: Path, source_profile: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    if (source_root / ".htaccess").exists():
        warnings.append(HTACCESS_RUNTIME_WARNING)
    if str(source_profile.get("preview_runtime_kind") or "") == "php":
        warnings.append(PHP_SERVICES_RUNTIME_WARNING)
    return warnings


def rendered_route_warnings(source_root: Path, source_profile: dict[str, object]) -> list[str]:
    return runtime_environment_warnings(source_root, source_profile)


def route_specific_warnings(warnings: list[object]) -> list[str]:
    clean: list[str] = []
    for warning in warnings:
        text = str(warning).strip()
        if text and text not in GLOBAL_RUNTIME_WARNINGS and text not in clean:
            clean.append(text)
    return clean


def _render_php_preview(
    data_root: Path,
    source_root: Path,
    *,
    route: str,
    source_profile: dict[str, object],
    artifact_ref: dict[str, object],
) -> dict[str, object]:
    php_missing = _php_missing_requirement("php")
    if php_missing:
        return _blocked_runtime("php", [php_missing], source_root, source_profile)
    runtime_root = _artifact_runtime_root(data_root, artifact_ref) or source_root
    docroot_rel = str(artifact_ref.get("docroot") or source_profile.get("php_docroot") or ".")
    docroot = (runtime_root / docroot_rel).resolve() if docroot_rel and docroot_rel != "." else runtime_root.resolve()
    if not docroot.exists():
        return _blocked_runtime("php", [f"PHP docroot `{docroot_rel}` was not found"], source_root, source_profile)
    router = _php_router(runtime_root)
    rendered = _request_php_route(runtime_root, docroot, router, route)
    fallback_warning = ""
    if router is not None and _php_ready_without_body(rendered):
        direct_rendered = _request_php_route(runtime_root, docroot, None, route)
        if _php_ready_with_body(direct_rendered):
            rendered = direct_rendered
            fallback_warning = "PHP router returned an empty response; preview used the configured PHP docroot directly"
    warnings = rendered_route_warnings(source_root, source_profile)
    if fallback_warning:
        warnings.append(fallback_warning)
    if rendered["status"] != "ready":
        details = [str(rendered.get("detail") or "PHP route render failed")]
        return {
            "status": "failed",
            "runtime_kind": "php",
            "html": runtime_diagnostic_html("Preview route failed", details),
            "title": "",
            "source_files": source_files_for_runtime_route(source_root, source_profile),
            "warnings": warnings + details,
            "missing_requirements": [],
            "http_status": rendered.get("http_status", 0),
        }
    html = str(rendered["html"])
    if not html.strip():
        details = ["PHP route returned an empty response; check the configured docroot and router"]
        return {
            "status": "failed",
            "runtime_kind": "php",
            "html": runtime_diagnostic_html("Preview route failed", details),
            "title": "",
            "source_files": source_files_for_runtime_route(source_root, source_profile),
            "warnings": warnings + details,
            "missing_requirements": [],
            "http_status": rendered.get("http_status", 0),
        }
    return {
        "status": "ready",
        "runtime_kind": "php",
        "html": html[:MAX_RENDER_BYTES],
        "raw_html": html[:MAX_RENDER_BYTES],
        "page_path": _runtime_page_path_for_route(route),
        "title": _html_title(html),
        "source_files": source_files_for_runtime_route(source_root, source_profile),
        "warnings": warnings,
        "missing_requirements": [],
        "http_status": rendered.get("http_status", 200),
    }


def _render_node_build_preview(
    data_root: Path,
    source_root: Path,
    *,
    route: str,
    source_profile: dict[str, object],
    artifact_ref: dict[str, object],
) -> dict[str, object]:
    runtime_root = _artifact_runtime_root(data_root, artifact_ref)
    if runtime_root is None:
        return _blocked_runtime("node_build", ["runtime build artifact is required before preview"], source_root, source_profile)
    html_path = _static_route_path(runtime_root, route)
    if html_path is None:
        return _blocked_runtime("node_build", [f"built artifact does not contain route `{route or '/'}`"], source_root, source_profile)
    html = html_path.read_text(encoding="utf-8")
    return {
        "status": "ready",
        "runtime_kind": "node_build",
        "html": html[:MAX_RENDER_BYTES],
        "raw_html": html[:MAX_RENDER_BYTES],
        "page_path": html_path.relative_to(runtime_root).as_posix(),
        "title": _html_title(html),
        "source_files": [html_path.relative_to(runtime_root).as_posix()],
        "warnings": [],
        "missing_requirements": [],
        "http_status": 200,
    }


def _php_ready_without_body(rendered: dict[str, object]) -> bool:
    return str(rendered.get("status") or "") == "ready" and not str(rendered.get("html") or "").strip()


def _php_ready_with_body(rendered: dict[str, object]) -> bool:
    try:
        http_status = int(rendered.get("http_status") or 0)
    except (TypeError, ValueError):
        http_status = 0
    return (
        str(rendered.get("status") or "") == "ready"
        and 200 <= http_status < 400
        and bool(str(rendered.get("html") or "").strip())
    )


def _request_php_route(runtime_root: Path, docroot: Path, router: Path | None, route: str) -> dict[str, object]:
    last_result: dict[str, object] = {}
    for attempt in range(2):
        try:
            server = _php_preview_server(runtime_root, docroot, router)
            result = _request_php_route_from_server(server, route)
        except (OSError, URLError, TimeoutError, subprocess.SubprocessError) as error:
            result = {"status": "failed", "detail": str(error), "http_status": 0}
            server = None
        last_result = result
        if result.get("status") == "ready":
            return result
        if attempt == 0 and int(result.get("http_status") or 0) == 0:
            if server is not None:
                _evict_php_preview_server(server.key)
            continue
        return result
    return last_result or {"status": "failed", "detail": "PHP route render failed", "http_status": 0}


def _request_php_route_from_server(server: PhpPreviewServer, route: str) -> dict[str, object]:
    server.last_used = time.time()
    _store_php_preview_server_registry(server)
    try:
        request_route = route if route.startswith("/") else f"/{route}"
        request = Request(f"http://127.0.0.1:{server.port}{request_route}", headers={"User-Agent": "WebsiteStudioPreview/1.0"})
        try:
            with urlopen(request, timeout=PHP_REQUEST_TIMEOUT_SECONDS) as response:
                content = response.read(MAX_RENDER_BYTES + 1)
                status = int(getattr(response, "status", 200))
        except HTTPError as error:
            content = error.read(MAX_RENDER_BYTES + 1)
            status = error.code
        if len(content) > MAX_RENDER_BYTES:
            return {"status": "failed", "detail": "rendered route exceeded preview byte limit", "http_status": status}
        text = content.decode("utf-8", errors="replace")
        if status >= 400:
            return {"status": "failed", "detail": f"PHP route returned HTTP {status}", "http_status": status, "html": text}
        return {"status": "ready", "html": text, "http_status": status}
    except (OSError, URLError, TimeoutError, subprocess.SubprocessError) as error:
        return {"status": "failed", "detail": str(error), "http_status": 0}


def _php_preview_server(runtime_root: Path, docroot: Path, router: Path | None) -> PhpPreviewServer:
    key = _php_server_key(runtime_root, docroot, router)
    with _PHP_PREVIEW_SERVERS_LOCK:
        _cleanup_php_preview_servers_locked()
        existing = _PHP_PREVIEW_SERVERS.get(key)
        if existing and _php_process_alive(existing.process, pid=existing.pid):
            existing.last_used = time.time()
            _store_php_preview_server_registry(existing)
            return existing
        if existing:
            _terminate_php_preview_server(existing)
            _PHP_PREVIEW_SERVERS.pop(key, None)
        registered = _load_php_preview_server_registry(key, runtime_root, docroot, router)
        if registered and _php_process_alive(registered.process, pid=registered.pid):
            registered.last_used = time.time()
            _store_php_preview_server_registry(registered)
            _PHP_PREVIEW_SERVERS[key] = registered
            return registered
        server = _start_php_preview_server(key, runtime_root, docroot, router)
        _PHP_PREVIEW_SERVERS[key] = server
        _store_php_preview_server_registry(server)
        return server


def _start_php_preview_server(key: str, runtime_root: Path, docroot: Path, router: Path | None) -> PhpPreviewServer:
    port = _free_port()
    command = [shutil.which("php") or "php", "-d", "variables_order=GPCS", "-S", f"127.0.0.1:{port}", "-t", str(docroot)]
    if router is not None:
        command.append(str(router))
    env = _safe_env()
    env["WEBSITE_STUDIO_PREVIEW"] = "1"
    process = subprocess.Popen(
        command,
        cwd=runtime_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        preexec_fn=_runtime_preexec(PHP_CPU_LIMIT_SECONDS, PHP_MEMORY_LIMIT_BYTES),
    )
    process_group_id = _runtime_process_group_id(process.pid)
    try:
        _wait_for_php(port)
    except Exception:
        _terminate_php_preview_server(
            PhpPreviewServer(
                key=key,
                port=port,
                pid=process.pid,
                process=process,
                runtime_root=runtime_root,
                docroot=docroot,
                router=router,
                last_used=time.time(),
                process_group_id=process_group_id,
            )
        )
        raise
    return PhpPreviewServer(
        key=key,
        port=port,
        pid=process.pid,
        process=process,
        runtime_root=runtime_root,
        docroot=docroot,
        router=router,
        last_used=time.time(),
        process_group_id=process_group_id,
    )


def _php_server_key(runtime_root: Path, docroot: Path, router: Path | None) -> str:
    router_text = str(router.resolve()) if router is not None else ""
    payload = f"{runtime_root.resolve()}\0{docroot.resolve()}\0{router_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _php_process_alive(process: subprocess.Popen | None, *, pid: int | None = None) -> bool:
    if process is not None:
        return process.poll() is None
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _runtime_preexec(cpu_seconds: int, memory_bytes: int) -> Callable[[], None] | None:
    if os.name != "posix":
        return None

    def prepare_child() -> None:
        os.setsid()
        _apply_posix_resource_limits(cpu_seconds=cpu_seconds, memory_bytes=memory_bytes)

    return prepare_child


def _runtime_process_group_id(pid: int) -> int | None:
    return pid if os.name == "posix" else None


def _apply_posix_resource_limits(*, cpu_seconds: int, memory_bytes: int) -> None:
    try:
        import resource  # noqa: PLC0415
    except ImportError:
        return
    _set_posix_soft_limit(resource, resource.RLIMIT_CPU, cpu_seconds)
    if hasattr(resource, "RLIMIT_AS"):
        _set_posix_soft_limit(resource, resource.RLIMIT_AS, memory_bytes)
    _set_posix_soft_limit(resource, resource.RLIMIT_NOFILE, MAX_RUNTIME_OPEN_FILES)
    if hasattr(resource, "RLIMIT_NPROC"):
        _set_posix_soft_limit(resource, resource.RLIMIT_NPROC, MAX_RUNTIME_PROCESSES)


def _set_posix_soft_limit(resource_module: object, limit: int, desired: int) -> None:
    try:
        soft, hard = resource_module.getrlimit(limit)
        infinity = resource_module.RLIM_INFINITY
        target = desired if hard == infinity else min(desired, hard)
        if soft == infinity or soft > target:
            resource_module.setrlimit(limit, (target, hard))
    except (OSError, ValueError):
        return


def _terminate_process(process: subprocess.Popen, *, process_group_id: int | None, grace_seconds: float = 2) -> tuple[str, str]:
    if process.poll() is not None:
        return "", ""
    pid = getattr(process, "pid", None)
    if not pid:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        return stdout or "", stderr or ""
    _signal_runtime_process(pid, signal.SIGTERM, process_group_id=process_group_id)
    try:
        stdout, stderr = process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        _signal_runtime_process(pid, signal.SIGKILL, process_group_id=process_group_id)
        stdout, stderr = process.communicate()
    return stdout or "", stderr or ""


def _signal_runtime_process(pid: int, signum: int, *, process_group_id: int | None = None) -> None:
    try:
        if os.name == "posix" and process_group_id:
            os.killpg(process_group_id, signum)
        else:
            os.kill(pid, signum)
    except ProcessLookupError:
        return
    except OSError:
        if os.name == "posix" and process_group_id:
            try:
                os.kill(pid, signum)
            except OSError:
                return


def _cleanup_php_preview_servers_locked() -> None:
    now = time.time()
    expired = [
        key
        for key, server in _PHP_PREVIEW_SERVERS.items()
        if not _php_process_alive(server.process, pid=server.pid) or now - server.last_used > PHP_SERVER_TTL_SECONDS
    ]
    for key in expired:
        server = _PHP_PREVIEW_SERVERS.pop(key, None)
        if server is not None:
            _terminate_php_preview_server(server)
    _cleanup_php_preview_server_registry(now=now)


def _evict_php_preview_server(key: str) -> None:
    with _PHP_PREVIEW_SERVERS_LOCK:
        server = _PHP_PREVIEW_SERVERS.pop(key, None)
        if server is not None:
            _terminate_php_preview_server(server)


def _terminate_php_preview_server(server: PhpPreviewServer) -> None:
    _delete_php_preview_server_registry(server.key)
    if server.process is not None:
        _terminate_process(server.process, process_group_id=server.process_group_id)
        return
    _signal_runtime_process(server.pid, signal.SIGTERM, process_group_id=server.process_group_id)


def _shutdown_php_preview_servers() -> None:
    with _PHP_PREVIEW_SERVERS_LOCK:
        servers = list(_PHP_PREVIEW_SERVERS.values())
        _PHP_PREVIEW_SERVERS.clear()
    for server in servers:
        _terminate_php_preview_server(server)


def _php_preview_registry_root() -> Path:
    root = Path(os.environ.get("TMPDIR") or "/tmp") / "website-studio-php-preview"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _php_preview_registry_path(key: str) -> Path:
    return _php_preview_registry_root() / f"{key}.json"


def _store_php_preview_server_registry(server: PhpPreviewServer) -> None:
    payload = {
        "schema": "website-studio.php-preview-server.v1",
        "key": server.key,
        "pid": server.pid,
        "port": server.port,
        "runtime_root": str(server.runtime_root),
        "docroot": str(server.docroot),
        "router": str(server.router) if server.router is not None else "",
        "last_used": server.last_used,
        "expires_at": server.last_used + PHP_SERVER_TTL_SECONDS,
        "process_group_id": server.process_group_id or 0,
    }
    try:
        path = _php_preview_registry_path(server.key)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        return


def _load_php_preview_server_registry(key: str, runtime_root: Path, docroot: Path, router: Path | None) -> PhpPreviewServer | None:
    try:
        payload = json.loads(_php_preview_registry_path(key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != "website-studio.php-preview-server.v1":
        return None
    if str(payload.get("key") or "") != key:
        return None
    try:
        pid = int(payload.get("pid") or 0)
        port = int(payload.get("port") or 0)
        process_group_id = int(payload.get("process_group_id") or 0)
        expires_at = float(payload.get("expires_at") or 0)
    except (TypeError, ValueError):
        return None
    if expires_at < time.time() or port <= 0 or pid <= 0:
        _delete_php_preview_server_registry(key)
        return None
    if str(Path(str(payload.get("runtime_root") or "")).resolve()) != str(runtime_root.resolve()):
        return None
    if str(Path(str(payload.get("docroot") or "")).resolve()) != str(docroot.resolve()):
        return None
    payload_router = str(payload.get("router") or "")
    if payload_router != (str(router.resolve()) if router is not None else ""):
        return None
    return PhpPreviewServer(
        key=key,
        port=port,
        pid=pid,
        process=None,
        runtime_root=runtime_root,
        docroot=docroot,
        router=router,
        last_used=float(payload.get("last_used") or time.time()),
        process_group_id=process_group_id or None,
    )


def _cleanup_php_preview_server_registry(*, now: float) -> None:
    try:
        paths = list(_php_preview_registry_root().glob("*.json"))
    except OSError:
        return
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        try:
            expires_at = float(payload.get("expires_at") or 0)
            pid = int(payload.get("pid") or 0)
            process_group_id = int(payload.get("process_group_id") or 0)
        except (TypeError, ValueError):
            expires_at = 0
            pid = 0
            process_group_id = 0
        if expires_at >= now and _php_process_alive(None, pid=pid):
            continue
        key = str(payload.get("key") or path.stem)
        server = PhpPreviewServer(
            key=key,
            port=int(payload.get("port") or 0),
            pid=pid,
            process=None,
            runtime_root=Path(str(payload.get("runtime_root") or ".")),
            docroot=Path(str(payload.get("docroot") or ".")),
            router=Path(str(payload.get("router"))) if payload.get("router") else None,
            last_used=float(payload.get("last_used") or 0),
            process_group_id=process_group_id or None,
        )
        _terminate_php_preview_server(server)


def _delete_php_preview_server_registry(key: str) -> None:
    try:
        _php_preview_registry_path(key).unlink()
    except OSError:
        return


def _runtime_page_path_for_route(route: str) -> str:
    path = urlsplit(str(route or "/")).path or "/"
    if path == "/":
        return "index.php"
    stripped = path.strip("/")
    if not stripped:
        return "index.php"
    try:
        clean = safe_relative_path(f"{stripped}/index.php" if path.endswith("/") else stripped)
    except ValueError:
        return "index.php"
    return clean


def _run_bounded_subprocess(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    cpu_seconds: int,
    memory_bytes: int,
    label: str,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=_safe_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=_runtime_preexec(cpu_seconds, memory_bytes),
    )
    process_group_id = _runtime_process_group_id(process.pid)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        stdout, stderr = _terminate_process(process, process_group_id=process_group_id)
        log = _bounded_log((stdout or "") + "\n" + (stderr or ""))
        message = f"{label} timed out after {timeout_seconds} seconds"
        if log:
            message += ":\n" + log
        raise ValueError(message) from error
    return subprocess.CompletedProcess(command, process.returncode, stdout or "", stderr or "")


def _run_npm_install(source_root: Path) -> str:
    if not (source_root / "package-lock.json").exists():
        raise ValueError("npm package-lock.json is required for dependency installation")
    npm = shutil.which("npm")
    if not npm:
        raise ValueError("npm executable is not available")
    result = _run_bounded_subprocess(
        [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=source_root,
        timeout_seconds=BUILD_TIMEOUT_SECONDS,
        cpu_seconds=BUILD_CPU_LIMIT_SECONDS,
        memory_bytes=BUILD_MEMORY_LIMIT_BYTES,
        label="npm ci",
    )
    if result.returncode != 0:
        raise ValueError("npm ci failed:\n" + _bounded_log(result.stdout + "\n" + result.stderr))
    return _bounded_log("$ npm ci --ignore-scripts --no-audit --no-fund\n" + result.stdout + "\n" + result.stderr)


def _run_allowlisted_command(source_root: Path, command: list[str]) -> str:
    if not command:
        return ""
    if command[0] == "rm":
        _run_safe_rm(source_root, command[1:])
        return "$ " + " ".join(command) + "\nremoved generated file"
    executable = _resolve_workspace_binary(source_root, command[0])
    result = _run_bounded_subprocess(
        [str(executable), *command[1:]],
        cwd=source_root,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        cpu_seconds=COMMAND_CPU_LIMIT_SECONDS,
        memory_bytes=COMMAND_MEMORY_LIMIT_BYTES,
        label=f"build command `{command[0]}`",
    )
    log = "$ " + " ".join(command) + "\n" + result.stdout + "\n" + result.stderr
    if result.returncode != 0:
        raise ValueError(f"build command `{command[0]}` failed:\n{_bounded_log(log)}")
    return _bounded_log(log)


def _expand_script(name: str, scripts: dict[str, object], *, stack: list[str]) -> list[list[str]]:
    if name in stack:
        raise ValueError("recursive npm script expansion is not allowed")
    raw = str(scripts.get(name) or "").strip()
    if not raw:
        raise ValueError(f"npm script `{name}` is required")
    commands: list[list[str]] = []
    for segment in _split_shell_and(raw):
        parts = shlex.split(segment)
        if len(parts) >= 3 and parts[0] == "npm" and parts[1] == "run":
            commands.extend(_expand_script(parts[2], scripts, stack=[*stack, name]))
            continue
        if not parts:
            continue
        if parts[0] in UNSUPPORTED_WORKSPACE_BUILD_BINARIES:
            raise ValueError(UNSUPPORTED_WORKSPACE_BUILD_BINARIES[parts[0]])
        if parts[0] not in ALLOWED_WORKSPACE_BUILD_BINARIES and parts[0] != "rm":
            raise ValueError(f"build command `{parts[0]}` is not allowlisted")
        if parts[0] == "rm":
            _validate_rm_command(parts)
        commands.append(parts)
    return commands


def _split_shell_and(script: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s+&&\s+", script) if part.strip()]


def _validate_rm_command(parts: list[str]) -> None:
    if len(parts) != 2:
        raise ValueError("rm build step may remove exactly one generated file")
    safe_relative_path(parts[1])


def _run_safe_rm(source_root: Path, paths: list[str]) -> None:
    if len(paths) != 1:
        raise ValueError("rm build step may remove exactly one generated file")
    rel_path = safe_relative_path(paths[0])
    target = (source_root / rel_path).resolve()
    root = source_root.resolve()
    if target != root and root not in target.parents:
        raise ValueError("rm build step escaped the source root")
    if target.exists() and target.is_file():
        target.unlink()


def _copy_runtime_artifact(source_root: Path, artifact_root: Path) -> None:
    ignored = shutil.ignore_patterns("node_modules", ".git", ".cache", ".npm", ".DS_Store")
    shutil.copytree(source_root, artifact_root, ignore=ignored)


def _resolve_workspace_binary(source_root: Path, name: str) -> Path:
    local = source_root / "node_modules" / ".bin" / name
    if local.exists():
        return local.resolve()
    raise ValueError(f"build command `{name}` is not installed in this site's local npm dependencies")


def _read_package_json(source_root: Path) -> dict[str, object]:
    path = source_root / "package.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("package.json is not valid JSON") from error
    return payload if isinstance(payload, dict) else {}


def _detect_package_manager(source_root: Path) -> str:
    if (source_root / "package-lock.json").exists():
        return "npm"
    if (source_root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (source_root / "yarn.lock").exists():
        return "yarn"
    if (source_root / "bun.lockb").exists():
        return "bun"
    return "npm" if (source_root / "package.json").exists() else ""


def _php_missing_requirement(runtime_kind: str) -> str:
    if runtime_kind == "php" and not shutil.which("php"):
        return "php executable is not available to the Website Studio preview runtime"
    return ""


def _php_router(runtime_root: Path) -> Path | None:
    for candidate in ("local/router.php", "router.php"):
        path = runtime_root / candidate
        if path.exists():
            return path
    return None


def _artifact_runtime_root(data_root: Path, artifact_ref: dict[str, object]) -> Path | None:
    rel = str(artifact_ref.get("runtime_root") or "").strip()
    if not rel:
        return None
    root = (data_root / rel).resolve()
    allowed = data_root.resolve()
    if root != allowed and allowed not in root.parents:
        raise ValueError("runtime artifact root escaped the Website Studio data root")
    return root if root.exists() else None


def _static_route_path(runtime_root: Path, route: str) -> Path | None:
    clean = route.strip() or "/"
    if clean == "/":
        candidates = ["index.html"]
    else:
        rel = safe_relative_path(clean.strip("/"))
        candidates = [rel, f"{rel}.html", f"{rel}/index.html"]
    for candidate in candidates:
        path = runtime_root / candidate
        if path.exists() and path.is_file() and path.suffix.lower() in {".html", ".htm"}:
            return path
    return None


def _blocked_runtime(runtime_kind: str, missing: list[str], source_root: Path, source_profile: dict[str, object]) -> dict[str, object]:
    return {
        "status": "blocked",
        "runtime_kind": runtime_kind,
        "html": runtime_diagnostic_html("Preview runtime unavailable", missing),
        "title": "",
        "source_files": source_files_for_runtime_route(source_root, source_profile),
        "warnings": rendered_route_warnings(source_root, source_profile),
        "missing_requirements": _dedupe(missing),
        "http_status": 0,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _wait_for_php(port: int) -> None:
    deadline = time.monotonic() + PHP_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
            handle.settimeout(0.25)
            if handle.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError("PHP preview server did not start")


def _safe_env() -> dict[str, str]:
    allowed = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "TMPDIR": os.environ.get("TMPDIR", ""),
        "CI": "true",
        "NO_COLOR": "1",
        "NPM_CONFIG_IGNORE_SCRIPTS": "true",
        "NPM_CONFIG_AUDIT": "false",
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        "WEBSITE_STUDIO_RUNTIME_POLICY": "bounded-subprocess-v1",
    }
    return {key: value for key, value in allowed.items() if value}


def _bounded_log(value: str) -> str:
    text = _redact_log(value)
    if len(text) > MAX_LOG_CHARS:
        return text[:MAX_LOG_CHARS] + "\n[truncated]"
    return text


def redact_runtime_log(value: str) -> str:
    return _redact_log(value)


def _redact_log(value: str) -> str:
    text = value
    text = re.sub(r"(?i)(token|secret|password|api[_-]?key)(=|:)\s*[^\s]+", r"\1\2[redacted]", text)
    text = re.sub(r"gh[pousr]_[A-Za-z0-9_]{20,}", "github_[redacted]", text)
    text = re.sub(r"(?<!:)/(?:home|tmp|var/tmp|private/tmp)/[^\s'\"<>]+", "[host-path]", text)
    return text


def internal_routes_from_html(html: str, *, base_route: str = "/") -> list[str]:
    parser = _InternalLinkParser()
    parser.feed(html[:MAX_RENDER_BYTES])
    routes: list[str] = []
    for href in parser.hrefs:
        route = _normalize_internal_route(href, base_route=base_route)
        if route and route not in routes:
            routes.append(route)
    return routes


def _normalize_internal_route(href: str, *, base_route: str) -> str:
    value = str(href or "").strip()
    if not value or value.startswith("#"):
        return ""
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return ""
    path = parsed.path.strip()
    if not path:
        return ""
    if path.startswith("/"):
        route = posixpath.normpath(path)
    else:
        base = str(base_route or "/").strip() or "/"
        if not base.startswith("/"):
            base = f"/{base}"
        if not base.endswith("/"):
            base = base.rsplit("/", 1)[0] + "/"
        route = posixpath.normpath(posixpath.join(base, path))
    if route in {"", "."}:
        route = "/"
    if not route.startswith("/"):
        route = f"/{route}"
    if route.endswith("/index.html"):
        route = route[: -len("index.html")] or "/"
    elif route.endswith(".html") and route != "/index.html":
        route = route[: -len(".html")] or "/"
    return route.rstrip("/") or "/"


def _html_title(html: str) -> str:
    parser = _TitleParser()
    parser.feed(html[:200000])
    return parser.title.strip()


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


class _InternalLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "area"}:
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = str(item or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result
