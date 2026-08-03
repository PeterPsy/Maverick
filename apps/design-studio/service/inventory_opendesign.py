#!/usr/bin/env python3
"""Create the pinned OpenDesign route and source supply-chain inventories.

The scanner intentionally reads a clean, exact upstream checkout instead of the
large curated runtime bundle.  It uses a small TypeScript lexical scanner so
the inventory can be regenerated with the Python standard library alone.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


UPSTREAM_COMMIT = "276b4d8e970bc143d7ad060181a89a834e3d9caf"
UPSTREAM_TAG = "open-design-v0.16.1"
UPSTREAM_VERSION = "0.16.1"
ROUTE_ROOT = Path("apps/daemon/src")
ROUTE_CALL = re.compile(
    r"\b(?P<receiver>app|router)\.(?P<method>get|post|put|patch|delete|options|head|use)\s*\("
)
STATIC_CONSTANT = re.compile(
    r"(?:export\s+)?const\s+(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)\s*[;\n]",
    re.DOTALL,
)


_DYNAMIC_ROUTE_EXPANSIONS = {
    ("apps/daemon/src/routes/chat.ts", "POST", "routePath"): (
        "/api/proxy/senseaudio/stream",
        "/api/proxy/aihubmix/stream",
    ),
}


_REGEX_ROUTE_TEMPLATES = {
    r"/^\/api\/projects\/([^/]+)\/text-preview\/(.+)$/u": "/api/projects/{project_id}/text-preview/{*project_path}",
    r"/^\/api\/projects\/([^/]+)\/preview\/([^/]+)\/(.+)$/u": "/api/projects/{project_id}/preview/{preview_id}/{*project_path}",
    r"/^\/api\/projects\/([^/]+)\/raw\/(.+)$/u": "/api/projects/{project_id}/raw/{*project_path}",
    r"/^\/api\/projects\/([^/]+)\/powered\/(.+)$/u": "/api/projects/{project_id}/powered/{*project_path}",
    r"/^\/api\/projects\/([^/]+)\/files\/(.+)\/versions$/u": "/api/projects/{project_id}/files/{*project_path}/versions",
    r"/^\/api\/projects\/([^/]+)\/files\/(.+)\/versions\/([^/]+)\/restore$/u": "/api/projects/{project_id}/files/{*project_path}/versions/{version_id}/restore",
    r"/^\/api\/projects\/([^/]+)\/files\/(.+)\/versions\/([^/]+)$/u": "/api/projects/{project_id}/files/{*project_path}/versions/{version_id}",
    r"/^\/api\/projects\/([^/]+)\/files\/(.+)$/u": "/api/projects/{project_id}/files/{*project_path}",
}


_BLOCKED_OWNER_PARTS = (
    "/connectors/",
    "/mcp-routes.ts",
    "/routes/automation.ts",
    "/routes/brand",
    "/routes/deploy.ts",
    "/routes/handoff.ts",
    "/routes/host-tools.ts",
    "/routes/library.ts",
    "/routes/live-artifact.ts",
    "/routes/memory.ts",
    "/routes/open-design-public-metadata.ts",
    "/routes/plugins/",
    "/routes/routine.ts",
    "/routes/social-share.ts",
    "/routes/telemetry.ts",
    "/routes/terminal.ts",
    "/routes/vela.ts",
    "/routes/whats-new.ts",
    "/routes/xai.ts",
)


_BLOCKED_PATH_PARTS = (
    "/agents/",
    "/analytics/",
    "/attribution/bridge-url",
    "/connectors",
    "/daemon/",
    "/deploy",
    "/diagnostics",
    "/dialog/",
    "/dir-exists",
    "/editors",
    "/figma/",
    "/import/claude-design",
    "/import/folder",
    "/integrations/",
    "/library/",
    "/marketplaces",
    "/mcp",
    "/media/generate",
    "/memory",
    "/metrics",
    "/oauth",
    "/observability/",
    "/open-in",
    "/orbit/",
    "/plugin",
    "/project-locations",
    "/proxy/",
    "/recent-dirs",
    "/research/",
    "/social-share",
    "/system/",
    "/telemetry",
    "/terminals",
    "/working-dir",
    "/xai/",
)


def _run_git(source: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _verify_source(source: Path) -> None:
    if _run_git(source, "rev-parse", "HEAD") != UPSTREAM_COMMIT:
        raise SystemExit(f"OpenDesign checkout must be at {UPSTREAM_COMMIT}.")
    if _run_git(source, "status", "--porcelain"):
        raise SystemExit("OpenDesign checkout must be clean.")
    resolved_tag = _run_git(source, "rev-list", "-n", "1", UPSTREAM_TAG)
    if resolved_tag != UPSTREAM_COMMIT:
        raise SystemExit(f"Tag {UPSTREAM_TAG} does not resolve to the pinned commit.")


def _tracked_files(source: Path) -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return sorted(item.decode("utf-8") for item in output.split(b"\0") if item)


def _route_source_files(source: Path) -> list[Path]:
    root = source / ROUTE_ROOT
    return sorted(path for path in root.rglob("*") if path.suffix in {".ts", ".tsx"})


def _static_constants(source: Path, tracked: Iterable[str]) -> dict[str, str]:
    constants: dict[str, str] = {}
    for relative in tracked:
        if not relative.endswith((".ts", ".tsx")):
            continue
        path = source / relative
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in STATIC_CONSTANT.finditer(text):
            constants.setdefault(match.group("name"), match.group("value"))
    return constants


def _first_argument(source: str, start: int) -> str:
    cursor = start
    stack: list[str] = []
    quote = ""
    escaped = False
    regex_literal = False
    regex_character_class = False
    while cursor < len(source):
        char = source[cursor]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            cursor += 1
            continue
        if regex_literal:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "[":
                regex_character_class = True
            elif char == "]":
                regex_character_class = False
            elif char == "/" and not regex_character_class:
                regex_literal = False
                cursor += 1
                while cursor < len(source) and source[cursor].isalpha():
                    cursor += 1
                continue
            cursor += 1
            continue
        if char in "'\"`":
            quote = char
        elif char == "/" and not source[start:cursor].strip():
            regex_literal = True
        elif char in "([{":
            stack.append(char)
        elif char in ")]}" and stack:
            stack.pop()
        elif char == "," and not stack:
            return source[start:cursor].strip()
        elif char == ")" and not stack:
            return source[start:cursor].strip()
        cursor += 1
    raise ValueError("unterminated Express route call")


def _decode_string(expression: str) -> str | None:
    if len(expression) < 2 or expression[0] not in "'\"`" or expression[-1] != expression[0]:
        return None
    value = expression[1:-1]
    if expression[0] == "`" and "${" in value:
        return None
    return bytes(value, "utf-8").decode("unicode_escape")


def _template_path(path: str) -> str:
    if path.startswith("<"):
        return path
    normalized = re.sub(r":([A-Za-z][A-Za-z0-9_]*)", r"{\1}", path)
    return re.sub(r"\*([A-Za-z][A-Za-z0-9_]*)", r"{*\1}", normalized)


def _resolve_paths(
    relative: str,
    method: str,
    expression: str,
    constants: dict[str, str],
) -> list[tuple[str, str]]:
    decoded = _decode_string(expression)
    if decoded is not None:
        return [(_template_path(decoded), "string")]
    if expression in constants:
        return [(_template_path(constants[expression]), f"constant:{expression}")]
    if expression in _REGEX_ROUTE_TEMPLATES:
        return [(_REGEX_ROUTE_TEMPLATES[expression], "regex-normalized")]
    expansion = _DYNAMIC_ROUTE_EXPANSIONS.get((relative, method, expression))
    if expansion:
        return [(_template_path(path), f"factory:{expression}") for path in expansion]
    return [(f"<unresolved:{expression}>", "unresolved")]


def _classify(owner: str, method: str, path: str) -> tuple[str, str]:
    lowered = path.lower()
    if path.startswith("<unresolved:"):
        return "blocked", "unresolved registrations are denied"
    if any(part in owner for part in _BLOCKED_OWNER_PARTS):
        return "blocked", "owner module is outside the approved product surface"
    if any(part in lowered for part in _BLOCKED_PATH_PARTS):
        return "blocked", "host, network, install, control-plane, or undeclared capability"
    if lowered.startswith("/api/provider") or lowered.startswith("/api/test/connection"):
        return "blocked", "provider and runtime authority remains Maverick-owned"
    if lowered in {"/api/media/config", "/api/app-config", "/api/attribution/claim"}:
        return "handled_by_core", "Maverick-owned configuration or actor attribution"
    if owner.endswith("/routes/media.ts"):
        return "blocked", "media/provider egress is not in the approved minimum route set"
    if owner.endswith("/routes/chat.ts"):
        if lowered == "/api/runs/{id}/feedback":
            return "pass_through", "run feedback is stored in the isolated OpenDesign domain"
        return "blocked", "legacy provider proxy or critique runtime path"
    if owner.endswith("/routes/daemon.ts"):
        if lowered in {"/api/health", "/api/ready", "/api/version"}:
            return "pass_through", "sidecar lifecycle metadata"
        return "blocked", "daemon administration is not browser-authorized"
    if owner.endswith("/routes/static-resource.ts"):
        if method in {"GET", "HEAD"}:
            return "pass_through", "approved bundled read-only resource"
        return "blocked", "bundled resources are read-only"
    if owner.endswith("/routes/design-systems.ts"):
        if method in {"GET", "HEAD"}:
            return "pass_through", "approved design-system read surface"
        return "blocked", "design-system mutation is outside the approved route minimum"
    if owner.endswith("/import-export-routes.ts"):
        if any(part in lowered for part in ("/import/", "/working-dir", "/finalize/")):
            return "blocked", "host import, rebinding, and provider finalize are brokered or denied"
        return "pass_through", "project-owned upload or export surface"
    if owner.endswith("/routes/project/index.ts") or owner.endswith("/routes/project/conversations.ts") or owner.endswith("/routes/project/comments.ts"):
        return "pass_through", "OpenDesign-owned project, conversation, or file surface"
    if owner.endswith("/routes/runs.ts") or owner.endswith("/routes/genui.ts"):
        return "pass_through", "OpenDesign-owned run, event, result, or preview surface"
    if owner.endswith("/static-spa.ts"):
        return "pass_through", "OpenDesign web application shell"
    if owner.endswith("/server.ts"):
        if lowered in {"/api/health", "/api/ready", "/api/version", "/api/preview/isolation", "/artifacts", "/frames"}:
            return "pass_through", "sidecar lifecycle or isolated static asset surface"
        return "blocked", "server-level route is not in the approved product surface"
    return "blocked", "route is not in the approved minimum and defaults closed"


def _route_inventory(source: Path, tracked: list[str]) -> dict[str, Any]:
    constants = _static_constants(source, tracked)
    routes: list[dict[str, Any]] = []
    for path in _route_source_files(source):
        relative = path.relative_to(source).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in ROUTE_CALL.finditer(text):
            expression = _first_argument(text, match.end())
            method = match.group("method").upper()
            if method == "USE" and not expression.startswith(("'", '"', "`", "/")):
                continue
            for template, path_source in _resolve_paths(relative, method, expression, constants):
                classification, rationale = _classify(relative, method, template)
                routes.append(
                    {
                        "method": method,
                        "path_template": template,
                        "owner": relative,
                        "line": text.count("\n", 0, match.start()) + 1,
                        "classification": classification,
                        "rationale": rationale,
                        "path_source": path_source,
                    }
                )
    routes.sort(key=lambda item: (item["path_template"], item["method"], item["owner"], item["line"]))
    unresolved = [route for route in routes if route["path_source"] == "unresolved"]
    if unresolved:
        detail = ", ".join(f"{item['owner']}:{item['line']}" for item in unresolved)
        raise SystemExit(f"Unresolved OpenDesign route registrations: {detail}")
    counts = Counter(route["classification"] for route in routes)
    return {
        "schema_version": "1",
        "upstream": {
            "tag": UPSTREAM_TAG,
            "commit": UPSTREAM_COMMIT,
            "release_version": UPSTREAM_VERSION,
        },
        "policy": {
            "default": "blocked",
            "precedence": ["blocked", "handled_by_core", "pass_through"],
            "scope": "browser-sidecar-origin",
            "note": "App-entrypoint capabilities use a separate, no-broader allowlist.",
        },
        "counts": {"total": len(routes), **dict(sorted(counts.items()))},
        "routes": routes,
    }


def _package_license_inventory(source: Path, tracked: list[str]) -> tuple[list[dict[str, str]], dict[str, int]]:
    packages: list[dict[str, str]] = []
    licenses: Counter[str] = Counter()
    for relative in tracked:
        if not relative.endswith("package.json"):
            continue
        payload = json.loads((source / relative).read_text(encoding="utf-8"))
        license_name = str(payload.get("license") or "UNDECLARED")
        licenses[license_name] += 1
        packages.append(
            {
                "path": relative,
                "name": str(payload.get("name") or ""),
                "version": str(payload.get("version") or ""),
                "license": license_name,
            }
        )
    return packages, dict(sorted(licenses.items()))


def _supply_chain_inventory(source: Path, tracked: list[str]) -> dict[str, Any]:
    packages, license_counts = _package_license_inventory(source, tracked)
    license_files = [
        relative
        for relative in tracked
        if Path(relative).name.upper().startswith(("LICENSE", "LICENCE", "NOTICE"))
    ]
    total_bytes = sum((source / relative).stat().st_size for relative in tracked)
    lockfile = source / "pnpm-lock.yaml"
    return {
        "schema_version": "1",
        "upstream": {
            "tag": UPSTREAM_TAG,
            "commit": UPSTREAM_COMMIT,
            "release_version": UPSTREAM_VERSION,
            "root_package_version": json.loads((source / "package.json").read_text(encoding="utf-8"))["version"],
        },
        "source_tree": {
            "tracked_file_count": len(tracked),
            "tracked_bytes": total_bytes,
            "package_count": len(packages),
            "pnpm_lock_sha256": hashlib.sha256(lockfile.read_bytes()).hexdigest(),
        },
        "packages": packages,
        "declared_license_counts": license_counts,
        "license_files": license_files,
        "native_runtime_dependencies": [
            {
                "name": "better-sqlite3",
                "version": "12.10.0",
                "reason": "native SQLite binding used by the daemon",
            },
            {
                "name": "node-pty",
                "version": "1.1.0",
                "reason": "native PTY binding; terminal routes are blocked but the daemon imports the package",
            },
            {
                "name": "blake3-wasm",
                "version": "2.1.5",
                "reason": "WebAssembly runtime dependency used by the daemon",
            },
        ],
        "build_native_dependencies": ["esbuild", "sharp"],
        "required_follow_up": [
            "WP5 emits the staged runtime-closure file manifest, SBOM, NOTICE, and license inventory.",
            "WP5 performs native load tests on every supported OS/architecture artifact.",
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--routes-output", type=Path, required=True)
    parser.add_argument("--supply-chain-output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    _verify_source(source)
    tracked = _tracked_files(source)
    _write_json(args.routes_output, _route_inventory(source, tracked))
    _write_json(args.supply_chain_output, _supply_chain_inventory(source, tracked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
