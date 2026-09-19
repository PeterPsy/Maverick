"""Static export asset policy and release-scoped URL preparation."""
from pathlib import Path, PurePosixPath
import re
import stat

MAX_FILES = 512
MAX_FILE = 2 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_ZIP = 2 * 1024 * 1024
EXTENSIONS = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".txt", ".svg", ".png", ".jpg",
              ".jpeg", ".webp", ".gif", ".ico", ".avif", ".woff", ".woff2", ".ttf", ".otf",
              ".mp4", ".webm", ".mp3", ".wav", ".pdf"}
EXCLUDED = {"node_modules", "src", "vendor", "package.json", "package-lock.json", "tsconfig.json", "composer.json", "composer.lock"}
TEXT = {".html", ".htm", ".css", ".js", ".mjs", ".svg", ".json"}
PRIVATE_ROUTES = re.compile(r"/(?:api/(?:apps|runtime|core|storage)|app/|apps/(?:storage|chat|website-studio))", re.I)
ROOT_URL = re.compile(r'''(["'(=])(/(?!/)[A-Za-z0-9_./@+?=&%# -]*)''')


class ExportError(ValueError):
    pass


def collect_files(root: Path):
    files = {}
    size = 0
    visited = 0
    # Bounded walk, never follow links or traverse development directories.
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            visited += 1
            if visited > 2048:
                raise ExportError("artifact_too_large")
            if path.name.startswith(".") or path.name in EXCLUDED or path.suffix.lower() == ".map":
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or (not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode)):
                raise ExportError("source_not_exportable")
            if path.is_dir():
                pending.append(path)
                continue
            if info.st_nlink != 1 or path.suffix.lower() not in EXTENSIONS:
                raise ExportError("source_not_exportable")
            name = path.relative_to(root).as_posix()
            if len(name) > 240 or not re.fullmatch(r"[A-Za-z0-9_./@+ -]+", name):
                raise ExportError("source_not_exportable")
            size += info.st_size
            if info.st_size > MAX_FILE or size > MAX_TOTAL or len(files) >= MAX_FILES:
                raise ExportError("artifact_too_large")
            with path.open("rb") as stream:
                content = stream.read(MAX_FILE + 1)
            if len(content) != info.st_size:
                raise ExportError("build_stale")
            files[name] = content
    if "index.html" not in files:
        raise ExportError("source_not_exportable")
    return files


def prepare_assets(files, release_id):
    prefix = f"/_releases/{release_id}/"
    prepared = {}
    for name, data in files.items():
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in TEXT:
            prepared[name] = data
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeError as error:
            raise ExportError("source_not_exportable") from error
        if PRIVATE_ROUTES.search(text) or "serviceWorker.register" in text:
            raise ExportError("source_not_exportable")
        if suffix in {".html", ".htm", ".css"} and re.search(r'''(?:src\s*=\s*["']|url\(\s*["']?|@import\s*["'])(?:https?:)?//''', text, re.I):
            raise ExportError("source_not_exportable")

        def rebase(match):
            quoted, path = match.groups()
            raw = re.split(r"[?#]", path, maxsplit=1)[0].lstrip("/")
            if raw in files or (raw.endswith("/") and any(item.startswith(raw) for item in files)):
                return quoted + prefix + path.lstrip("/")
            # Root application routes are valid; a missing local asset is not.
            if PurePosixPath(raw).suffix.lower() in EXTENSIONS:
                raise ExportError("source_not_exportable")
            return match.group(0)

        text = ROOT_URL.sub(rebase, text)
        if suffix in {".html", ".htm"}:
            if re.search(r"<base\b", text, re.I):
                raise ExportError("source_not_exportable")
            parent = str(PurePosixPath(name).parent)
            base = prefix + (parent + "/" if parent != "." else "")
            tag = f'<base href="{base}">'
            head = re.search(r"<head\b[^>]*>", text, re.I)
            if head:
                text = text[:head.end()] + tag + text[head.end():]
            else:
                # Valid HTML without an explicit head: insert a head after html/doctype.
                start = re.search(r"<html\b[^>]*>|<!doctype[^>]*>", text, re.I)
                offset = start.end() if start else 0
                text = text[:offset] + "<head>" + tag + "</head>" + text[offset:]
        prepared[name] = text.encode("utf-8")
    if sum(map(len, prepared.values())) > MAX_TOTAL or any(len(data) > MAX_FILE for data in prepared.values()):
        raise ExportError("artifact_too_large")
    return prepared
