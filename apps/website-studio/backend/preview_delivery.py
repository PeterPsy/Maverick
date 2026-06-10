"""Preview document and asset URL rewriting for Website Studio."""

from __future__ import annotations

import base64
import posixpath
import re
from pathlib import PurePosixPath
from typing import Callable
from urllib.parse import parse_qs, quote, urlencode, urlparse, unquote

from safety import safe_relative_path


PREVIEW_MEDIA_PATH = "/api/apps/website-studio/backend/media"
PREVIEW_FILE_GATEWAY_PATH = "/api/apps/website-studio/backend/file/"
PREVIEW_ORIGIN_PLACEHOLDER = "__WEBSITE_STUDIO_PREVIEW_ORIGIN__"
PREVIEW_MEDIA_SOURCE_PLACEHOLDER = "__WEBSITE_STUDIO_PREVIEW_MEDIA_SOURCE__"
PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER = "__WEBSITE_STUDIO_PREVIEW_FILE_GATEWAY_SOURCE__"
PREVIEW_BACKEND_SOURCE_PLACEHOLDER = "__WEBSITE_STUDIO_PREVIEW_BACKEND_SOURCE__"

ASSET_SUFFIXES = {
    ".avif",
    ".css",
    ".gif",
    ".ico",
    ".jpg",
    ".jpeg",
    ".js",
    ".mjs",
    ".mp3",
    ".mp4",
    ".oga",
    ".ogg",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".ttf",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
}
PARENT_RELATIVE_ASSET_ROOTS = frozenset({"assets", "css", "dist", "fonts", "images", "js", "media"})


def preview_media_url(preview_id: object, asset_path: object, *, asset_query: str = "", with_origin_placeholder: bool = False) -> str:
    query = {
        "preview_id": str(preview_id or ""),
        "path": safe_preview_asset_path(asset_path),
    }
    if asset_query:
        query["asset_query"] = asset_query
    prefix = f"{PREVIEW_ORIGIN_PLACEHOLDER}{PREVIEW_MEDIA_PATH}" if with_origin_placeholder else PREVIEW_MEDIA_PATH
    return f"{prefix}?{urlencode(query)}"


def safe_preview_asset_path(raw_path: object) -> str:
    text = str(raw_path or "").replace("\\", "/").strip()
    while text.startswith("/"):
        text = text[1:]
    parsed = urlparse(text)
    if parsed.scheme or parsed.netloc:
        raise ValueError("preview asset path must be local")
    path = unquote(parsed.path or "")
    return safe_relative_path(path)


AssetTextLoader = Callable[[str], tuple[str, str] | None]


def prepare_preview_document_html(
    html: object,
    *,
    preview_id: object,
    page_path: object = None,
    preview_origin: object = None,
    stylesheet_loader: AssetTextLoader | None = None,
    script_loader: AssetTextLoader | None = None,
) -> str:
    text = str(html if html is not None else "")
    text = _remove_existing_csp(text)
    text = _rewrite_html_tags(text, preview_id=preview_id, page_path=page_path)
    text = _rewrite_style_blocks(text, preview_id=preview_id, base_path=page_path or "index.html", with_origin_placeholder=True)
    if stylesheet_loader is not None:
        text = _inline_stylesheet_links(text, stylesheet_loader=stylesheet_loader, preview_origin=preview_origin)
    text = _rewrite_inline_script_asset_refs(text, preview_id=preview_id, base_path=page_path or "index.html")
    if script_loader is not None:
        text = _inline_script_srcs(text, script_loader=script_loader, preview_origin=preview_origin)
    text = _inject_preview_csp(text)
    origin = _safe_preview_origin(preview_origin)
    if origin:
        text = text.replace(PREVIEW_ORIGIN_PLACEHOLDER, origin)
        text = text.replace(PREVIEW_MEDIA_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_MEDIA_PATH}")
        text = text.replace(PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_FILE_GATEWAY_PATH}")
        text = text.replace(PREVIEW_BACKEND_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_FILE_GATEWAY_PATH}")
    return text


def rewrite_preview_css(css: str, *, preview_id: object, css_path: object = None, with_origin_placeholder: bool = False) -> str:
    return _rewrite_css_urls(css, preview_id=preview_id, base_path=css_path or "index.css", with_origin_placeholder=with_origin_placeholder)


def _rewrite_html_tags(html: str, *, preview_id: object, page_path: object) -> str:
    def replace_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        tag_name = match.group(1).lower()
        attrs = _html_attrs(tag)

        def replace_attr(attr_match: re.Match[str]) -> str:
            name = attr_match.group(1)
            quote_char = attr_match.group(2)
            value = attr_match.group(3)
            lowered = name.lower()
            if lowered in {"srcset", "data-srcset"} and _attr_references_asset(tag_name, lowered, attrs):
                rewritten_srcset = _rewrite_srcset(value, preview_id=preview_id, base_path=page_path, with_origin_placeholder=True)
                return f"{name}={quote_char}{rewritten_srcset}{quote_char}"
            if lowered == "style":
                rewritten_style = _rewrite_css_urls(value, preview_id=preview_id, base_path=page_path or "index.html", with_origin_placeholder=True)
                return f"{name}={quote_char}{rewritten_style}{quote_char}"
            if tag_name == "a" and lowered == "href":
                anchor = _same_page_anchor(value)
                if anchor is not None:
                    return f"{name}={quote_char}{anchor}{quote_char}"
            if not _attr_references_asset(tag_name, lowered, attrs):
                return attr_match.group(0)
            rewritten = _rewrite_asset_ref(value, preview_id=preview_id, base_path=page_path, with_origin_placeholder=True)
            if rewritten == value:
                return attr_match.group(0)
            return f"{name}={quote_char}{rewritten}{quote_char}"

        return re.sub(r"(?is)\b([a-z0-9_:-]+)\s*=\s*([\"'])(.*?)\2", replace_attr, tag)

    return re.sub(r"(?is)<([a-z0-9:-]+)\b[^>]*>", replace_tag, html)


def _rewrite_style_blocks(html: str, *, preview_id: object, base_path: object, with_origin_placeholder: bool = False) -> str:
    def replace(match: re.Match[str]) -> str:
        css = match.group(2)
        rewritten = _rewrite_css_urls(css, preview_id=preview_id, base_path=base_path, with_origin_placeholder=with_origin_placeholder)
        return f"{match.group(1)}{rewritten}{match.group(3)}"

    return re.sub(r"(?is)(<style\b[^>]*>)(.*?)(</style\s*>)", replace, html)


def _rewrite_inline_script_asset_refs(html: str, *, preview_id: object, base_path: object) -> str:
    def replace_script(match: re.Match[str]) -> str:
        opening = match.group(1)
        script = match.group(2)
        closing = match.group(3)
        attrs = _html_attrs(opening)
        script_type = attrs.get("type", "").strip().lower()
        if script_type and script_type not in {"application/javascript", "module", "text/javascript"}:
            return match.group(0)
        rewritten = _rewrite_js_asset_assignments(script, preview_id=preview_id, base_path=base_path)
        return f"{opening}{rewritten}{closing}"

    return re.sub(r"(?is)(<script\b(?![^>]*\bsrc\s*=)[^>]*>)(.*?)(</script\s*>)", replace_script, html)


def _rewrite_js_asset_assignments(script: str, *, preview_id: object, base_path: object) -> str:
    def replace_property(match: re.Match[str]) -> str:
        prefix = match.group(1)
        quote_char = match.group(2)
        value = match.group(3)
        rewritten = _rewrite_asset_ref(value, preview_id=preview_id, base_path=base_path, with_origin_placeholder=True)
        return f"{prefix}{quote_char}{rewritten}{quote_char}"

    script = re.sub(r"(?is)(\.(?:src|href)\s*=\s*)([\"'])(.*?)\2", replace_property, script)

    def replace_set_attribute(match: re.Match[str]) -> str:
        prefix = match.group(1)
        quote_char = match.group(2)
        value = match.group(3)
        rewritten = _rewrite_asset_ref(value, preview_id=preview_id, base_path=base_path, with_origin_placeholder=True)
        return f"{prefix}{quote_char}{rewritten}{quote_char}"

    return re.sub(
        r"(?is)(\.setAttribute\(\s*[\"'](?:src|href)[\"']\s*,\s*)([\"'])(.*?)\2",
        replace_set_attribute,
        script,
    )


def _inline_stylesheet_links(html: str, *, stylesheet_loader: AssetTextLoader, preview_origin: object = None) -> str:
    origin = _safe_preview_origin(preview_origin)

    def replace_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        attrs = _html_attrs(tag)
        rel = {part.strip().lower() for part in attrs.get("rel", "").split()}
        href = attrs.get("href", "")
        if "stylesheet" not in rel or not href:
            return tag
        asset_path = _preview_media_asset_path(href)
        if not asset_path:
            return tag
        try:
            loaded = stylesheet_loader(asset_path)
        except (OSError, ValueError):
            return tag
        if loaded is None:
            return tag
        css, source_path = loaded
        if origin:
            css = css.replace(PREVIEW_ORIGIN_PLACEHOLDER, origin)
            css = css.replace(PREVIEW_MEDIA_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_MEDIA_PATH}")
            css = css.replace(PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_FILE_GATEWAY_PATH}")
            css = css.replace(PREVIEW_BACKEND_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_FILE_GATEWAY_PATH}")
        media_attr = f' media="{_escape_attr(attrs["media"])}"' if attrs.get("media") else ""
        source_attr = _escape_attr(source_path or asset_path)
        return f'<style data-website-studio-inline-stylesheet="{source_attr}"{media_attr}>{_safe_style_text(css)}</style>'

    return re.sub(r"(?is)<link\b[^>]*>", replace_tag, html)


def _inline_script_srcs(html: str, *, script_loader: AssetTextLoader, preview_origin: object = None) -> str:
    origin = _safe_preview_origin(preview_origin)
    inlined = False

    def replace_script(match: re.Match[str]) -> str:
        nonlocal inlined
        opening = match.group(1)
        attrs = _html_attrs(opening)
        src = attrs.get("src", "")
        if not src:
            return match.group(0)
        script_type = attrs.get("type", "").strip().lower()
        if script_type and script_type not in {"application/javascript", "module", "text/javascript"}:
            return match.group(0)
        asset_path = _preview_media_asset_path(src)
        if not asset_path:
            return match.group(0)
        try:
            loaded = script_loader(asset_path)
        except (OSError, ValueError):
            return match.group(0)
        if loaded is None:
            return match.group(0)
        script, source_path = loaded
        if origin:
            script = script.replace(PREVIEW_ORIGIN_PLACEHOLDER, origin)
            script = script.replace(PREVIEW_MEDIA_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_MEDIA_PATH}")
            script = script.replace(PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_FILE_GATEWAY_PATH}")
            script = script.replace(PREVIEW_BACKEND_SOURCE_PLACEHOLDER, f"{origin}{PREVIEW_FILE_GATEWAY_PATH}")
        inlined = True
        script_type_attr = f' data-preview-script-type="{_escape_attr(attrs["type"])}"' if attrs.get("type") else ""
        source_attr = _escape_attr(source_path or asset_path)
        encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
        return (
            f'<script type="application/x-website-studio-inline-script" '
            f'data-website-studio-inline-script="{source_attr}"{script_type_attr}>{encoded}</script>'
        )

    rewritten = re.sub(r"(?is)(<script\b[^>]*\bsrc\s*=\s*([\"']).*?\2[^>]*>).*?</script\s*>", replace_script, html)
    return _append_inline_script_runner(rewritten) if inlined else rewritten


def _append_inline_script_runner(html: str) -> str:
    shim = (
        '<script data-website-studio-preview-shim>'
        "(() => {"
        "const createStorage = () => {"
        "const values = new Map();"
        "return {"
        "get length() { return values.size; },"
        "key: (index) => Array.from(values.keys())[index] || null,"
        "getItem: (key) => values.has(String(key)) ? values.get(String(key)) : null,"
        "setItem: (key, value) => { values.set(String(key), String(value)); },"
        "removeItem: (key) => { values.delete(String(key)); },"
        "clear: () => { values.clear(); }"
        "};"
        "};"
        "for (const name of ['localStorage', 'sessionStorage']) {"
        "try { void window[name]; }"
        "catch {"
        "try { Object.defineProperty(window, name, { value: createStorage(), configurable: true }); }"
        "catch {}"
        "}"
        "}"
        "})();"
        "</script>"
    )
    runner = (
        '<script data-website-studio-inline-script-runner>'
        "(() => {"
        "const decode = (value) => {"
        "const binary = atob(value || '');"
        "const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));"
        "return new TextDecoder().decode(bytes);"
        "};"
        "for (const source of Array.from(document.querySelectorAll('script[type=\"application/x-website-studio-inline-script\"]'))) {"
        "const script = document.createElement('script');"
        "const scriptType = source.getAttribute('data-preview-script-type') || '';"
        "if (scriptType) script.type = scriptType;"
        "script.textContent = decode(source.textContent || '');"
        "source.replaceWith(script);"
        "}"
        "})();"
        "</script>"
    )
    lazy_assets = (
        '<script data-website-studio-preview-lazy-assets>'
        "(() => {"
        "const triggerViewportWork = () => {"
        "try { window.dispatchEvent(new Event('resize')); } catch {}"
        "try { window.dispatchEvent(new Event('scroll')); } catch {}"
        "};"
        "const promoteImage = (image) => {"
        "if (!image || image.dataset.websiteStudioPreviewLoaded === '1') return;"
        "const src = image.getAttribute('data-src');"
        "const srcset = image.getAttribute('data-srcset');"
        "if (!src && !srcset) return;"
        "image.dataset.websiteStudioPreviewLoaded = '1';"
        "image.addEventListener('load', () => image.classList.add('loaded'), { once: true });"
        "image.addEventListener('error', () => image.classList.add('error'), { once: true });"
        "if (srcset) { image.setAttribute('srcset', srcset); image.removeAttribute('data-srcset'); }"
        "if (src) { image.setAttribute('src', src); image.removeAttribute('data-src'); }"
        "};"
        "const promoteBackground = (element) => {"
        "if (!element || element.dataset.websiteStudioPreviewBgLoaded === '1') return;"
        "const src = element.getAttribute('data-bg');"
        "if (!src) return;"
        "element.dataset.websiteStudioPreviewBgLoaded = '1';"
        "element.style.backgroundImage = `url(\"${src}\")`;"
        "element.classList.add('bg-loaded');"
        "element.removeAttribute('data-bg');"
        "const image = new Image();"
        "image.onerror = () => element.classList.add('bg-error');"
        "image.src = src;"
        "};"
        "const promoteNearbyVideos = () => {"
        "const viewportHeight = Math.max(window.innerHeight || 0, document.documentElement.clientHeight || 0);"
        "for (const video of Array.from(document.querySelectorAll('video[data-src]'))) {"
        "const rect = video.getBoundingClientRect();"
        "if (rect.top > viewportHeight * 1.5) continue;"
        "const src = video.getAttribute('data-src');"
        "if (!src) continue;"
        "video.setAttribute('src', src);"
        "video.removeAttribute('data-src');"
        "try { video.load(); } catch {}"
        "}"
        "};"
        "const hydrate = () => {"
        "triggerViewportWork();"
        "window.setTimeout(() => {"
        "triggerViewportWork();"
        "for (const image of Array.from(document.querySelectorAll('img[data-src], img[data-srcset]'))) promoteImage(image);"
        "for (const element of Array.from(document.querySelectorAll('[data-bg]'))) promoteBackground(element);"
        "promoteNearbyVideos();"
        "}, 1200);"
        "};"
        "if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', hydrate, { once: true });"
        "else hydrate();"
        "})();"
        "</script>"
    )
    payload = shim + runner + lazy_assets
    body_match = re.search(r"(?is)</body\s*>", html)
    if body_match:
        return html[: body_match.start()] + payload + html[body_match.start() :]
    return html + payload


def _preview_media_asset_path(value: str) -> str:
    ref = str(value or "").strip()
    if ref.startswith(PREVIEW_ORIGIN_PLACEHOLDER):
        ref = ref[len(PREVIEW_ORIGIN_PLACEHOLDER) :]
    parsed = urlparse(ref)
    if parsed.scheme or parsed.netloc:
        if parsed.path != PREVIEW_MEDIA_PATH:
            return ""
    elif parsed.path != PREVIEW_MEDIA_PATH:
        return ""
    params = parse_qs(parsed.query, keep_blank_values=True)
    raw_path = params.get("path", [""])[0]
    if not raw_path:
        return ""
    try:
        return safe_preview_asset_path(raw_path)
    except ValueError:
        return ""


def _safe_style_text(value: str) -> str:
    return str(value or "").replace("</", "<\\/")




def _rewrite_css_urls(css: str, *, preview_id: object, base_path: object, with_origin_placeholder: bool = False) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_value = match.group(2).strip()
        if _skip_ref(raw_value):
            return match.group(0)
        rewritten = _rewrite_asset_ref(raw_value, preview_id=preview_id, base_path=base_path, with_origin_placeholder=with_origin_placeholder)
        if rewritten == raw_value:
            return match.group(0)
        return f'url("{rewritten}")'

    return re.sub(r"(?is)url\(\s*([\"']?)(.*?)\1\s*\)", replace, css)


def _rewrite_srcset(value: str, *, preview_id: object, base_path: object, with_origin_placeholder: bool = False) -> str:
    candidates: list[str] = []
    for raw_candidate in value.split(","):
        candidate = raw_candidate.strip()
        if not candidate:
            continue
        parts = candidate.split()
        if not parts:
            continue
        parts[0] = _rewrite_asset_ref(parts[0], preview_id=preview_id, base_path=base_path, with_origin_placeholder=with_origin_placeholder)
        candidates.append(" ".join(parts))
    return ", ".join(candidates)


def _rewrite_asset_ref(value: str, *, preview_id: object, base_path: object, with_origin_placeholder: bool = False) -> str:
    normalized = _normal_preview_ref(value, base_path)
    if normalized is None:
        return value
    rel_path, asset_query, fragment = normalized
    rewritten = preview_media_url(preview_id, rel_path, asset_query=asset_query, with_origin_placeholder=with_origin_placeholder)
    return f"{rewritten}#{quote(fragment, safe='/:?=&%')}" if fragment else rewritten


def _normal_preview_ref(value: str, base_path: object) -> tuple[str, str, str] | None:
    ref = str(value or "").strip()
    if _skip_ref(ref):
        return None
    parsed = urlparse(ref)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path or "")
    if not path:
        return None
    if path.startswith("/"):
        candidate = path.lstrip("/")
    else:
        candidate = _normalize_relative_asset_path(path, base_path)
        if candidate is None:
            return None
    try:
        clean = safe_relative_path(candidate)
    except ValueError:
        return None
    return clean, parsed.query or "", parsed.fragment or ""


def _normalize_relative_asset_path(path: str, base_path: object) -> str | None:
    base_dir = PurePosixPath(str(base_path or "index.html")).parent.as_posix()
    joined = posixpath.join("" if base_dir == "." else base_dir, path)
    normalized = posixpath.normpath(joined).lstrip("/")
    if _relative_path_stays_inside_site(normalized):
        return normalized
    fallback = _parent_relative_asset_root(path)
    if fallback:
        return fallback
    return None


def _relative_path_stays_inside_site(path: str) -> bool:
    return path not in {"", "."} and path != ".." and not path.startswith("../")


def _parent_relative_asset_root(path: str) -> str | None:
    stripped = str(path or "").replace("\\", "/").lstrip("/")
    saw_parent = False
    while stripped.startswith("../"):
        stripped = stripped[3:]
        saw_parent = True
    if not saw_parent:
        return None
    normalized = posixpath.normpath(stripped).lstrip("/")
    if not _relative_path_stays_inside_site(normalized):
        return None
    first_segment = normalized.split("/", 1)[0]
    if first_segment not in PARENT_RELATIVE_ASSET_ROOTS:
        return None
    return normalized


def _attr_references_asset(tag_name: str, attr_name: str, attrs: dict[str, str]) -> bool:
    if attr_name in {"src", "poster", "srcset", "data-src", "data-srcset", "data-bg", "data-background", "data-poster"}:
        return tag_name in {"audio", "embed", "img", "picture", "script", "source", "track", "video"} or attr_name.startswith("data-")
    if attr_name != "href":
        return False
    if tag_name != "link":
        return _has_asset_suffix(attrs.get("href", ""))
    rel = {part.strip().lower() for part in attrs.get("rel", "").split()}
    as_value = attrs.get("as", "").strip().lower()
    if rel & {"stylesheet", "icon", "apple-touch-icon", "manifest", "modulepreload"}:
        return True
    if "preload" in rel or "prefetch" in rel:
        return not as_value or as_value in {"audio", "font", "image", "script", "style", "track", "video"}
    return _has_asset_suffix(attrs.get("href", ""))


def _has_asset_suffix(value: str) -> bool:
    path = urlparse(str(value or "")).path
    return PurePosixPath(path).suffix.lower() in ASSET_SUFFIXES


def _same_page_anchor(value: str) -> str | None:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme or parsed.netloc or not parsed.fragment:
        return None
    path = (parsed.path or "").strip()
    if path in {"", "/", "/index.php", "index.php", "/index.html", "index.html"}:
        return "#" + parsed.fragment
    return None


def _skip_ref(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered or lowered.startswith(("#", "data:", "blob:", "mailto:", "tel:", "javascript:", "about:")):
        return True
    return any(marker in value for marker in ("{", "}", "$(", "${", "var("))


def _safe_preview_origin(value: object) -> str:
    text = str(value or "").strip()
    if not text or any(char in text for char in "\r\n\t"):
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _html_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"(?is)\b([a-z0-9_:-]+)\s*=\s*([\"'])(.*?)\2", tag):
        attrs[match.group(1).lower()] = match.group(3)
    return attrs


def _remove_existing_csp(html: str) -> str:
    return re.sub(
        r"(?is)<meta\b[^>]*http-equiv\s*=\s*([\"'])content-security-policy\1[^>]*>",
        "",
        html,
    )


def _inject_preview_csp(html: str) -> str:
    csp = (
        "default-src 'none'; "
        f"img-src data: blob: https: {PREVIEW_MEDIA_SOURCE_PLACEHOLDER} {PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER}; "
        f"media-src data: blob: https: {PREVIEW_MEDIA_SOURCE_PLACEHOLDER} {PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER}; "
        f"font-src data: blob: https: {PREVIEW_MEDIA_SOURCE_PLACEHOLDER} {PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER}; "
        f"style-src 'unsafe-inline' blob: https: {PREVIEW_MEDIA_SOURCE_PLACEHOLDER} {PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER}; "
        f"script-src 'unsafe-inline' blob: {PREVIEW_MEDIA_SOURCE_PLACEHOLDER} {PREVIEW_FILE_GATEWAY_SOURCE_PLACEHOLDER}; "
        "connect-src 'none'; frame-ancestors 'self'; form-action 'none'; base-uri 'none'"
    )
    metas = ""
    if not re.search(r"(?is)<meta\b[^>]*\bcharset\s*=", html):
        metas += '<meta charset="utf-8">'
    metas += '<meta http-equiv="Content-Security-Policy" content="' + _escape_attr(csp) + '">'
    head_match = re.search(r"(?i)<head[^>]*>", html)
    if head_match:
        return html[: head_match.end()] + metas + html[head_match.end() :]
    return "<!doctype html><html><head>" + metas + "</head><body>" + html + "</body></html>"


def _escape_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("'", "&#39;")
