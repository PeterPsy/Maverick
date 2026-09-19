"""Read-only public request resolution, independent of the private control plane."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import re
from threading import Lock
import time

from external_apps.artifacts import load_manifest
from external_apps.bindings import read_binding
from external_apps.errors import AppError
from external_apps.files import read_regular
from external_apps.policy import HEADERS, MAX_FILE, canonical_host, canonical_path, domain_name, identifier


class VerifiedCache:
    """Bounded bytes cache; authority is checked afresh before every access."""
    def __init__(self):
        self.items = OrderedDict()
        self.bytes = 0
        self.lock = Lock()

    def read(self, path, expected, limit=MAX_FILE):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise AppError("unsafe_filesystem", 503)
        info = path.stat()
        key = (str(path), expected, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        with self.lock:
            cached = self.items.get(key)
            if cached is not None:
                self.items.move_to_end(key)
                return cached
        content = read_regular(path, limit)
        if hashlib.sha256(content).hexdigest() != expected:
            raise AppError("corrupt_artifact", 503)
        with self.lock:
            if key not in self.items:
                self.items[key] = content
                self.bytes += len(content)
            while len(self.items) > 128 or self.bytes > 32 * 1024 * 1024:
                _, removed = self.items.popitem(last=False)
                self.bytes -= len(removed)
        return content


class PublicRuntime:
    def __init__(self, *, domain: str, mounts: dict[str, Path], projection: Path):
        self.domain = domain_name(domain)
        self.mounts = {identifier(key, length=12): Path(value) for key, value in mounts.items()}
        if len(self.mounts) > 64:
            raise AppError("too_many_mounts")
        self.projection = projection
        self.cache = VerifiedCache()

    def response(self, method, host, target, headers=None):
        headers = headers or {}
        try:
            if method not in {"GET", "HEAD"}:
                return self.error(405, "method_not_allowed", {"Allow": "GET, HEAD"})
            hostname = canonical_host(host, self.domain)
            label = hostname[:-(len(self.domain) + 1)]
            match = re.fullmatch(r"[a-z0-9-]+-([a-f0-9]{32})", label)
            if match is None:
                raise AppError("not_found", 404)
            public_id = match[1]
            namespace = public_id[:12]
            authority = json.loads(read_regular(self.projection, 16384))
            now = time.time()
            if (authority.get("version") != 1 or authority.get("domain") != self.domain
                    or not now < authority.get("expires", 0) <= now + 10
                    or namespace not in authority.get("namespaces", [])):
                raise AppError("unavailable", 503)
            root = self.mounts.get(namespace)
            if root is None:
                raise AppError("not_found", 404)
            binding = read_binding(root, public_id)
            if binding.get("hostname") != hostname:
                raise AppError("not_found", 404)
            if not binding["enabled"] or binding["archived"]:
                raise AppError("unavailable", 503)
            path = canonical_path(target)
            release = binding["current"]
            if path.startswith("/_releases/"):
                parts = path.split("/", 3)
                if len(parts) != 4:
                    raise AppError("not_found", 404)
                identifier(parts[2], "rel_")
                release = next((item for item in (binding["current"], binding["previous"])
                                if item and item["release_id"] == parts[2]), None)
                if release is None:
                    raise AppError("not_found", 404)
                path = "/" + parts[3]
            if (path.split("/")[1] in {"api", "app", "apps", "mcp", "cli", "_releases"}
                    or any(part.startswith(".") for part in path.split("/") if part)):
                raise AppError("not_found", 404)
            manifest = load_manifest(root, release["digest"], release["manifest_digest"])
            name = path.lstrip("/")
            files = manifest["files"]
            if not name:
                name = manifest["entrypoint"]
            elif name.endswith("/"):
                name += "index.html"
            elif name not in files and name + "/index.html" in files:
                name += "/index.html"
            elif name not in files and name + ".html" in files:
                name += ".html"
            if name not in files:
                navigation = "text/html" in str(headers.get("accept", ""))
                if release["format"] == "spa_bundle" and navigation and "." not in path.rsplit("/", 1)[-1]:
                    name = manifest["entrypoint"]
                else:
                    raise AppError("not_found", 404)
            item = files[name]
            content = self.cache.read(root / "artifacts" / release["digest"] / "files" / name, item["sha256"])
            if len(content) != item["size"]:
                raise AppError("corrupt_artifact", 503)
            etag = '"' + item["sha256"] + '"'
            response_headers = {**HEADERS, "Content-Type": item["mime"], "ETag": etag,
                                "Content-Length": str(len(content)), "X-External-Release": release["release_id"]}
            if headers.get("if-none-match") == etag:
                response_headers.pop("Content-Length")
                return 304, response_headers, b""
            return 200, response_headers, b"" if method == "HEAD" else content
        except AppError as error:
            return self.error(error.status, error.code)
        except (OSError, ValueError, KeyError, TypeError):
            return self.error(503, "unavailable")

    @staticmethod
    def error(status, code, extra=None):
        content = (code + "\n").encode()
        return status, {**HEADERS, "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8",
                        "Content-Length": str(len(content)), **(extra or {})}, content
