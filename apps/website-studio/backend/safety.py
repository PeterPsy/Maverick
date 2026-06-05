"""Path, ZIP, and text safety helpers for Website Studio."""

from __future__ import annotations

import base64
import hashlib
import io
import mimetypes
import re
import shutil
from urllib.parse import unquote, urlparse
import zipfile
from pathlib import Path, PurePosixPath


IGNORED_ZIP_NAMES = {".DS_Store", "Thumbs.db"}
BLOCKED_SOURCE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
EXECUTABLE_EXTENSIONS = {
    ".appimage",
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".msi",
    ".ps1",
    ".scr",
}
MAX_ZIP_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_ZIP_FILES = 800
MAX_ZIP_EXPANDED_BYTES = 30 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 10 * 1024 * 1024
MAX_SOURCE_TREE_FILES = MAX_ZIP_FILES
MAX_SOURCE_TREE_BYTES = 200 * 1024 * 1024
MAX_TEXT_FILE_BYTES = 512 * 1024
MAX_PREVIEW_ASSET_BYTES = 2 * 1024 * 1024
MAX_PREVIEW_TOTAL_ASSET_BYTES = 4 * 1024 * 1024
MAX_PREVIEW_SCRIPT_BYTES = 512 * 1024
MAX_PREVIEW_TOTAL_SCRIPT_BYTES = 1024 * 1024
TEXT_EXTENSIONS = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".txt",
    ".xml",
    ".svg",
    ".sh",
}
STATIC_ASSET_EXTENSIONS = {
    ".avif",
    ".css",
    ".gif",
    ".ico",
    ".jpg",
    ".jpeg",
    ".otf",
    ".png",
    ".svg",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
}
SOURCE_CONFIG_NAMES = {
    "astro.config.mjs",
    "astro.config.js",
    "gatsby-config.ts",
    "gatsby-config.js",
    "next.config.mjs",
    "next.config.ts",
    "next.config.js",
    "package.json",
    "vite.config.js",
    "vite.config.ts",
}
GIT_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,180}$")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "site"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_relative_path(raw_path: object) -> str:
    path = str(raw_path or "").replace("\\", "/").strip()
    if not path:
        raise ValueError("path is required")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"Unsafe website path `{path}`")
    return pure.as_posix()


def resolve_site_path(site_root: Path, raw_path: object) -> Path:
    rel_path = safe_relative_path(raw_path)
    target = (site_root / rel_path).resolve()
    root = site_root.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Path escapes the selected site: `{rel_path}`")
    return target


def read_text_file(path: Path) -> str:
    if path.stat().st_size > MAX_TEXT_FILE_BYTES:
        raise ValueError("file is too large for text editing")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("file is not valid UTF-8 text") from error


def write_text_file(path: Path, content: object) -> None:
    text = str(content if content is not None else "")
    if len(text.encode("utf-8")) > MAX_TEXT_FILE_BYTES:
        raise ValueError("file is too large for text editing")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def is_text_path(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def validate_editable_text_path(rel_path: str, *, size_bytes: int = 0) -> None:
    path = Path(rel_path)
    _validate_source_member(path.name, size_bytes, rel_path)
    if not is_text_path(path):
        raise ValueError(f"file `{rel_path}` is not a supported Website Studio text file")


def snapshot_text_files(source_root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not source_root.exists():
        return snapshot
    for path in sorted(source_root.rglob("*")):
        if path.is_file() and is_text_path(path) and path.stat().st_size <= MAX_TEXT_FILE_BYTES:
            rel_path = path.relative_to(source_root).as_posix()
            snapshot[rel_path] = read_text_file(path)
    return snapshot


def replace_tree_from_snapshot(source_root: Path, snapshot: dict[str, str]) -> None:
    if source_root.exists():
        shutil.rmtree(source_root)
    source_root.mkdir(parents=True, exist_ok=True)
    for rel_path, content in snapshot.items():
        write_text_file(resolve_site_path(source_root, rel_path), content)


def copy_tree_snapshot(source_root: Path, snapshot_root: Path) -> None:
    validate_source_tree_for_phase1(source_root)
    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    snapshot_root.parent.mkdir(parents=True, exist_ok=True)
    if source_root.exists():
        shutil.copytree(source_root, snapshot_root, symlinks=False)
    else:
        snapshot_root.mkdir(parents=True, exist_ok=True)


def replace_tree_from_directory(source_root: Path, snapshot_root: Path) -> None:
    validate_source_tree_for_phase1(snapshot_root)
    if source_root.exists():
        shutil.rmtree(source_root)
    source_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot_root, source_root, symlinks=False)


def validate_source_tree_for_phase1(source_root: Path) -> None:
    if not source_root.exists():
        return
    file_count = 0
    expanded_bytes = 0
    for path in source_root.rglob("*"):
        rel_path = path.relative_to(source_root).as_posix()
        if path.is_symlink():
            raise ValueError(f"source contains unsupported symlink `{rel_path}`")
        if path.is_file():
            size_bytes = path.stat().st_size
            file_count += 1
            if file_count > MAX_SOURCE_TREE_FILES:
                raise ValueError(f"source contains too many files; limit is {MAX_SOURCE_TREE_FILES}")
            expanded_bytes += size_bytes
            if expanded_bytes > MAX_SOURCE_TREE_BYTES:
                raise ValueError("source tree expanded size exceeds the Website Studio limit")
            if _is_filesystem_executable(path):
                raise ValueError(f"source contains unsupported executable file `{rel_path}`")
            _validate_source_member(path.name, size_bytes, rel_path)


def preview_srcdoc_html(html: object, *, source_root: Path | None = None, page_path: object = None) -> str:
    text = str(html if html is not None else "")
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script\s*>", "", text)
    text = re.sub(r"(?is)\s+on[a-z0-9_-]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", text)
    if source_root is not None:
        text = _inline_stylesheets(text, source_root, page_path)
        text = _inline_media_assets(text, source_root, page_path)
    csp = (
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src &#39;none&#39;; img-src data: blob:; style-src &#39;unsafe-inline&#39;; '
        'font-src data:; media-src data: blob:; frame-ancestors &#39;self&#39;; form-action &#39;none&#39;; base-uri &#39;none&#39;">'
    )
    head_match = re.search(r"(?i)<head[^>]*>", text)
    if head_match:
        return text[: head_match.end()] + csp + text[head_match.end() :]
    return "<!doctype html><html><head>" + csp + "</head><body>" + text + "</body></html>"


def runtime_srcdoc_html(html: object, *, source_root: Path, page_path: object = None) -> str:
    """Prepare runnable static preview HTML for an opaque-origin sandbox iframe."""
    text = str(html if html is not None else "")
    text = _inline_stylesheets(text, source_root, page_path)
    text = _inline_runtime_scripts(text, source_root, page_path)
    text = _inline_media_assets(text, source_root, page_path)
    csp = (
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src &#39;none&#39;; img-src data: blob:; style-src &#39;unsafe-inline&#39;; '
        'font-src data:; media-src data: blob:; script-src &#39;unsafe-inline&#39;; connect-src &#39;none&#39;; '
        'frame-ancestors &#39;self&#39;; form-action &#39;none&#39;; base-uri &#39;none&#39;">'
    )
    head_match = re.search(r"(?i)<head[^>]*>", text)
    if head_match:
        return text[: head_match.end()] + csp + text[head_match.end() :]
    return "<!doctype html><html><head>" + csp + "</head><body>" + text + "</body></html>"


def runtime_diagnostic_html(title: str, details: list[str]) -> str:
    items = "".join(f"<li>{_escape_html(item)}</li>" for item in details[:20])
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<style>body{margin:0;background:#080808;color:#ececec;font:14px system-ui,sans-serif;}"
        "main{display:grid;place-content:center;min-height:100vh;padding:32px;}"
        "section{max-width:720px;border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:18px;background:rgba(255,255,255,.055);}"
        "h1{margin:0 0 10px;font-size:18px;font-weight:600;}li{margin:6px 0;color:rgba(236,236,236,.72);}</style>"
        f"<title>{_escape_html(title)}</title></head><body><main><section><h1>{_escape_html(title)}</h1><ul>{items}</ul></section></main></body></html>"
    )


def extract_zip_base64(archive_base64: object, destination: Path) -> dict[str, object]:
    encoded = str(archive_base64 or "")
    if not encoded:
        raise ValueError("archive_base64 is required")
    try:
        archive_bytes = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError("archive_base64 is not valid base64") from error
    if len(archive_bytes) > MAX_ZIP_ARCHIVE_BYTES:
        raise ValueError("ZIP archive exceeds the Website Studio compressed size limit")

    destination.mkdir(parents=True, exist_ok=True)
    extracted_files = 0
    expanded_bytes = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as error:
        raise ValueError("archive_base64 is not a valid ZIP archive") from error

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > MAX_ZIP_FILES:
            raise ValueError(f"ZIP contains too many files; limit is {MAX_ZIP_FILES}")
        for info in infos:
            rel_path = _safe_zip_member_path(info.filename)
            if rel_path is None:
                continue
            if _is_zip_symlink(info):
                raise ValueError(f"ZIP contains unsupported symlink `{info.filename}`")
            if _is_zip_executable(info):
                raise ValueError(f"ZIP contains unsupported executable file `{info.filename}`")
            _validate_source_member(PurePosixPath(rel_path).name, info.file_size, rel_path)
            expanded_bytes += info.file_size
            if expanded_bytes > MAX_ZIP_EXPANDED_BYTES:
                raise ValueError("ZIP expanded size exceeds the Website Studio limit")
            target = resolve_site_path(destination, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted_files += 1
    if extracted_files == 0:
        raise ValueError("ZIP did not contain website files")
    _collapse_single_directory_root(destination)
    return {"files_extracted": extracted_files, "expanded_bytes": expanded_bytes, "source_shape": classify_source_tree(destination)}


def validate_git_source(repository_url: object, branch: object = None, *, data_root: Path | None = None) -> tuple[str, str]:
    source = str(repository_url or "").strip()
    if not source:
        raise ValueError("repository_url is required")
    if source.startswith("-"):
        raise ValueError("repository_url is invalid")
    parsed = urlparse(source)
    if parsed.scheme == "https" and parsed.netloc:
        if "@" in parsed.netloc:
            raise ValueError("repository_url must not include inline credentials")
        if parsed.netloc.lower() != "github.com":
            raise ValueError("Phase 1 Git imports only support GitHub HTTPS URLs or app-local repository paths")
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError("repository_url must not include params, query, or fragment")
        if not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?", parsed.path):
            raise ValueError("repository_url must be a GitHub owner/repository HTTPS URL")
        source = source.rstrip("/")
    elif parsed.scheme in {"http", "ssh", "git"} or re.match(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:.+", source):
        raise ValueError("Phase 1 Git imports only support GitHub HTTPS URLs or app-local repository paths")
    else:
        candidate = Path(source).expanduser()
        if not candidate.exists():
            raise ValueError("repository_url must be an HTTPS, SSH, git, or existing local repository path")
        if data_root is not None:
            resolved = candidate.resolve()
            root = data_root.resolve()
            if resolved != root and root not in resolved.parents:
                raise ValueError("local repository imports must stay inside the Website Studio data root")
        source = str(candidate.resolve())

    clean_branch = str(branch or "").strip()
    if clean_branch:
        if clean_branch.startswith("-") or ".." in clean_branch or not GIT_BRANCH_PATTERN.match(clean_branch):
            raise ValueError("branch contains unsupported characters")
    return source, clean_branch


def classify_source_tree(source_root: Path) -> str:
    if not source_root.exists():
        return "empty"
    file_names = {path.name for path in source_root.rglob("*") if path.is_file()}
    if file_names & SOURCE_CONFIG_NAMES:
        return "full_source"
    if any(path.suffix.lower() in {".html", ".htm"} for path in source_root.rglob("*") if path.is_file()):
        return "static_export"
    return "partial_source"


def source_profile(source_root: Path) -> dict[str, object]:
    shape = classify_source_tree(source_root)
    paths = [path.relative_to(source_root).as_posix() for path in source_root.rglob("*") if path.is_file()] if source_root.exists() else []
    files = {Path(path).name for path in paths}
    framework = "static"
    if any(name.startswith("next.config.") for name in files):
        framework = "next"
    elif any(name.startswith("astro.config.") for name in files):
        framework = "astro"
    elif any(name.startswith("gatsby-config.") for name in files):
        framework = "gatsby"
    elif any(name.startswith("vite.config.") for name in files):
        framework = "vite"

    package_manager = ""
    for lockfile, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
        ("bun.lockb", "bun"),
    ):
        if lockfile in files:
            package_manager = manager
            break
    if not package_manager and "package.json" in files:
        package_manager = "npm"

    static_preview_supported = any(Path(path).suffix.lower() in {".html", ".htm"} for path in paths)
    php_paths = [path for path in paths if Path(path).suffix.lower() == ".php"]
    php_docroot = _detect_php_docroot(php_paths)
    has_package_manifest = "package.json" in files
    if php_paths:
        runtime_kind = "php"
    elif has_package_manifest:
        runtime_kind = "node_build"
    elif static_preview_supported:
        runtime_kind = "static_export"
    else:
        runtime_kind = "unavailable"

    runtime_status = "static_fallback" if static_preview_supported else "blocked"
    runtime_supported = runtime_kind in {"static_export", "php", "node_build"}
    missing_requirements: list[str] = []
    if runtime_kind == "static_export" and static_preview_supported:
        runtime_status = "ready"
    elif runtime_kind == "unavailable":
        missing_requirements.append("static HTML route or supported preview runtime")
        runtime_supported = False

    return {
        "source_shape": shape,
        "framework": framework,
        "package_manager": package_manager,
        "has_package_manifest": has_package_manifest,
        "static_preview_supported": static_preview_supported,
        "preview_runtime_kind": runtime_kind,
        "runtime_preview_supported": runtime_supported,
        "runtime_preview_status": runtime_status,
        "php_docroot": php_docroot,
        "missing_requirements": missing_requirements,
    }


def _detect_php_docroot(php_paths: list[str]) -> str:
    if not php_paths:
        return ""
    candidates = ("frontend-website", "public", "www", "htdocs", "web")
    for candidate in candidates:
        if any(path == f"{candidate}/index.php" or path.startswith(f"{candidate}/") for path in php_paths):
            return candidate
    return "."


def detect_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def asset_references_from_html(html: str, *, page_path: object = None) -> list[str]:
    refs: list[str] = []
    page_dir = PurePosixPath(str(page_path or "index.html")).parent
    for tag_match in re.finditer(r"(?is)<(img|source|video|audio|script|link)\b[^>]*>", html):
        tag = tag_match.group(0)
        tag_name = tag_match.group(1).lower()
        attrs = _html_attrs(tag)
        raw_ref = attrs.get("src") or attrs.get("poster")
        if tag_name == "link" and _link_references_asset(attrs):
            raw_ref = attrs.get("href")
        if not raw_ref:
            continue
        ref = _normal_asset_ref(raw_ref, page_dir)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _safe_zip_member_path(filename: str) -> str | None:
    normalized = filename.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"ZIP contains unsafe path `{filename}`")
    if pure.parts and pure.parts[0] == "__MACOSX":
        return None
    if pure.name in IGNORED_ZIP_NAMES:
        return None
    return pure.as_posix()


def _collapse_single_directory_root(destination: Path) -> None:
    children = list(destination.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        return
    root = children[0]
    for child in list(root.iterdir()):
        child.replace(destination / child.name)
    root.rmdir()


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _is_zip_executable(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return bool(mode & 0o111)


def _is_filesystem_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def _validate_source_member(name: str, size_bytes: int, rel_path: str) -> None:
    if PurePosixPath(name).name in BLOCKED_SOURCE_NAMES:
        raise ValueError(f"source contains unsupported sensitive file `{rel_path}`")
    if PurePosixPath(name).suffix.lower() in EXECUTABLE_EXTENSIONS:
        raise ValueError(f"source contains unsupported executable file `{rel_path}`")
    if size_bytes > MAX_ZIP_MEMBER_BYTES:
        raise ValueError(f"source file `{rel_path}` exceeds the Website Studio per-file limit")


def _inline_stylesheets(html: str, source_root: Path, page_path: object) -> str:
    page_dir = PurePosixPath(str(page_path or "index.html")).parent

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _html_attrs(tag)
        if attrs.get("rel", "").lower() != "stylesheet" or "href" not in attrs:
            return tag
        rel_path = _normal_asset_ref(attrs["href"], page_dir)
        if not rel_path:
            return tag
        target = resolve_site_path(source_root, rel_path)
        if not target.exists() or target.suffix.lower() != ".css" or target.stat().st_size > MAX_TEXT_FILE_BYTES:
            return ""
        css = read_text_file(target).replace("</style", "<\\/style")
        return f"<style>{css}</style>"

    return re.sub(r"(?is)<link\b[^>]*>", replace, html)


def _inline_media_assets(html: str, source_root: Path, page_path: object) -> str:
    page_dir = PurePosixPath(str(page_path or "index.html")).parent
    budget = {"used": 0}

    def replace(match: re.Match[str]) -> str:
        attr = match.group(1)
        quote = match.group(2)
        value = match.group(3)
        rel_path = _normal_asset_ref(value, page_dir)
        if not rel_path:
            return match.group(0)
        target = resolve_site_path(source_root, rel_path)
        if not target.exists() or not target.is_file() or target.suffix.lower() not in STATIC_ASSET_EXTENSIONS:
            return match.group(0)
        size = target.stat().st_size
        if size > MAX_PREVIEW_ASSET_BYTES or budget["used"] + size > MAX_PREVIEW_TOTAL_ASSET_BYTES:
            return match.group(0)
        budget["used"] += size
        encoded = base64.b64encode(target.read_bytes()).decode("ascii")
        return f'{attr}={quote}data:{detect_content_type(target)};base64,{encoded}{quote}'

    return re.sub(r"(?is)\b(src|poster)\s*=\s*([\"'])(.*?)\2", replace, html)


def _inline_runtime_scripts(html: str, source_root: Path, page_path: object) -> str:
    page_dir = PurePosixPath(str(page_path or "index.html")).parent
    budget = {"used": 0}

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _html_attrs(tag)
        raw_src = attrs.get("src", "")
        if not raw_src:
            return tag
        rel_path = _normal_asset_ref(raw_src, page_dir)
        if not rel_path:
            return ""
        target = resolve_site_path(source_root, rel_path)
        if not target.exists() or not target.is_file() or target.suffix.lower() not in {".js", ".mjs"}:
            return ""
        size = target.stat().st_size
        if size > MAX_PREVIEW_SCRIPT_BYTES or budget["used"] + size > MAX_PREVIEW_TOTAL_SCRIPT_BYTES:
            return ""
        budget["used"] += size
        script = read_text_file(target).replace("</script", "<\\/script")
        return f"<script>{script}</script>"

    return re.sub(r"(?is)<script\b[^>]*\bsrc\s*=\s*([\"']).*?\1[^>]*>\s*</script\s*>", replace, html)


def _html_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"(?is)\b([a-z0-9_-]+)\s*=\s*([\"'])(.*?)\2", tag):
        attrs[match.group(1).lower()] = match.group(3)
    return attrs


def _link_references_asset(attrs: dict[str, str]) -> bool:
    rel = {part.strip().lower() for part in attrs.get("rel", "").split()}
    as_value = attrs.get("as", "").lower()
    return bool(rel & {"stylesheet", "icon", "preload", "modulepreload"}) and (not as_value or as_value in {"style", "font", "image", "script"})


def _normal_asset_ref(raw_ref: str, page_dir: PurePosixPath) -> str | None:
    ref = raw_ref.strip()
    if not ref:
        return None
    parsed = urlparse(ref)
    if parsed.scheme or parsed.netloc or ref.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
        return None
    path = unquote(parsed.path or "")
    if not path:
        return None
    if path.startswith("/"):
        path = path.lstrip("/")
        if not path:
            return None
        try:
            return safe_relative_path(path)
        except ValueError:
            return None
    try:
        return safe_relative_path((page_dir / path).as_posix())
    except ValueError:
        return None


def _escape_html(value: object) -> str:
    text = str(value if value is not None else "")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
