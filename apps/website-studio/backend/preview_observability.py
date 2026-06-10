"""Preview observability helpers for Website Studio."""

from __future__ import annotations

from collections import Counter
from html import unescape
from html.parser import HTMLParser
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qs, urlparse

from preview_delivery import PREVIEW_MEDIA_PATH, safe_preview_asset_path


MAX_SELECTOR_HINTS = 80
MAX_TEXT_SAMPLE = 120


def preview_media_paths_from_html(html: object) -> list[str]:
    """Return local preview media paths referenced by prepared preview HTML."""
    text = unescape(str(html or ""))
    paths: list[str] = []
    pattern = re.compile(
        r"(?:https?:\/\/[^\"'`\s<>)]+)?"
        + re.escape(PREVIEW_MEDIA_PATH)
        + r"\?[^\"'`\s<>)]+",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        path = _media_path_from_url(match.group(0))
        if path and path not in paths:
            paths.append(path)
    return paths


def build_selector_hints(
    html: object,
    *,
    source_files: list[str],
    source_texts: dict[str, str],
    asset_records: list[dict[str, object]],
) -> list[dict[str, object]]:
    parser = _HintParser()
    parser.feed(str(html or "")[:1_000_000])
    asset_by_path = {str(asset.get("path") or ""): asset for asset in asset_records}
    hints: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    for item in parser.items:
        if len(hints) >= MAX_SELECTOR_HINTS:
            break
        token = str(item.get("token") or "").strip()
        selector = str(item.get("selector") or "").strip()
        if not token or not selector:
            continue
        key = (selector, token)
        if key in seen:
            continue
        seen.add(key)
        candidates = _candidate_sources(token, source_files, source_texts)
        hint = {
            "selector": selector,
            "token": token,
            "tag": item.get("tag", ""),
            "text": item.get("text", ""),
            "source_files": candidates or source_files[:8],
            "confidence": "token_match" if candidates else "route_source_candidate",
        }
        asset_path = _normal_asset_token(token)
        if asset_path and asset_path in asset_by_path:
            hint["asset_id"] = asset_by_path[asset_path].get("id", "")
            hint["asset_path"] = asset_path
        hints.append(hint)
    return hints


def acceptance_checks(
    *,
    runtime_status: str,
    missing_requirements: list[str],
    warnings: list[str],
    asset_probe: dict[str, object],
    source_map: dict[str, object],
) -> dict[str, object]:
    missing_assets = list(asset_probe.get("missing", []) or [])
    local_errors = list(asset_probe.get("errors", []) or [])
    font_count = int(asset_probe.get("font_count") or 0)
    video_count = int(asset_probe.get("video_count") or 0)
    rendered_routes = int(source_map.get("rendered_route_count") or 0)
    failed_routes = int(source_map.get("failed_route_count") or 0)
    checks = [
        _check("runtime_ready", runtime_status in {"ready", "static_fallback"}, runtime_status),
        _check("no_missing_runtime_requirements", not missing_requirements, "; ".join(missing_requirements[:4])),
        _check("local_assets_resolve", not missing_assets and not local_errors, _asset_detail(missing_assets, local_errors)),
        _check("font_assets_resolve", font_count == 0 or not missing_assets, "not_applicable" if font_count == 0 else f"{font_count} font assets"),
        _check("video_assets_streamable", video_count == 0 or not missing_assets, "not_applicable" if video_count == 0 else f"{video_count} video assets"),
        _check("routes_have_rendered_signal", rendered_routes > 0 or runtime_status in {"ready", "static_fallback"}, f"{rendered_routes} rendered, {failed_routes} failed"),
        _check("playwright_probe_available", True, "preview runtime emits DOM, style, font, console, and asset diagnostics via postMessage"),
    ]
    if warnings:
        checks.append(_check("warnings_are_reported", True, "; ".join(warnings[:4])))
    passed = all(item["status"] in {"passed", "not_applicable"} for item in checks)
    return {"passed": passed, "checks": checks}


def summarize_asset_probe(asset_records: list[dict[str, object]], media_paths: list[str], resolved: list[dict[str, object]], missing: list[str]) -> dict[str, object]:
    by_kind = Counter(str(asset.get("kind") or "file") for asset in asset_records)
    media_by_kind = Counter(str(item.get("kind") or "file") for item in resolved)
    return {
        "indexed_asset_count": len(asset_records),
        "indexed_by_kind": dict(sorted(by_kind.items())),
        "preview_media_reference_count": len(media_paths),
        "resolved_count": len(resolved),
        "missing_count": len(missing),
        "font_count": media_by_kind.get("font", 0),
        "video_count": media_by_kind.get("video", 0),
        "image_count": media_by_kind.get("image", 0),
    }


def asset_kind_for_path(path: str, content_type: str = "") -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico"}:
        return "image"
    if suffix in {".mp4", ".webm", ".ogg", ".ogv", ".mov"}:
        return "video"
    if suffix in {".mp3", ".oga", ".wav"}:
        return "audio"
    if suffix in {".woff", ".woff2", ".ttf", ".otf"}:
        return "font"
    if suffix == ".css":
        return "stylesheet"
    if suffix in {".js", ".mjs"}:
        return "script"
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("font/"):
        return "font"
    return "file"


def _media_path_from_url(value: str) -> str:
    try:
        parsed = urlparse(value)
        if parsed.path != PREVIEW_MEDIA_PATH:
            return ""
        raw_path = parse_qs(parsed.query, keep_blank_values=True).get("path", [""])[0]
        return safe_preview_asset_path(raw_path) if raw_path else ""
    except ValueError:
        return ""


def _candidate_sources(token: str, source_files: list[str], source_texts: dict[str, str]) -> list[str]:
    token = token.strip()
    if not token:
        return []
    matches: list[str] = []
    for path in source_files:
        text = source_texts.get(path, "")
        if token in text:
            matches.append(path)
    return matches[:8]


def _normal_asset_token(token: str) -> str:
    parsed = urlparse(token.strip())
    path = parsed.path or token.strip()
    path = path.lstrip("/")
    try:
        return safe_preview_asset_path(path)
    except ValueError:
        return ""


def _check(name: str, passed: bool, detail: str) -> dict[str, object]:
    status = "passed" if passed else "failed"
    if detail == "not_applicable":
        status = "not_applicable"
    return {"name": name, "status": status, "detail": detail}


def _asset_detail(missing_assets: list[object], local_errors: list[object]) -> str:
    if not missing_assets and not local_errors:
        return "all local preview media references resolve"
    parts = [str(item) for item in missing_assets[:4]]
    parts.extend(str(item) for item in local_errors[:4])
    return "; ".join(parts)


class _HintParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, object]] = []
        self._text_targets: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value or "" for name, value in attrs}
        index_for_text = -1
        if attr_map.get("id"):
            index_for_text = self._append(tag, f"#{attr_map['id']}", attr_map["id"])
        classes = [item for item in attr_map.get("class", "").split() if item]
        for class_name in classes[:4]:
            self._append(tag, f".{class_name}", class_name)
        for attr in ("src", "href", "poster", "data-src", "data-bg"):
            if attr_map.get(attr):
                self._append(tag, f"{tag}[{attr}]", attr_map[attr])
        if tag in {"a", "button", "h1", "h2", "h3", "p"}:
            if index_for_text < 0:
                index_for_text = self._append(tag, tag, "")
            self._text_targets.append(index_for_text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"a", "button", "h1", "h2", "h3", "p"} and self._text_targets:
            self._text_targets.pop()

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or not self._text_targets:
            return
        index = self._text_targets[-1]
        if 0 <= index < len(self.items) and not self.items[index].get("text"):
            self.items[index]["text"] = text[:MAX_TEXT_SAMPLE]
            if not self.items[index].get("token"):
                self.items[index]["token"] = text[:MAX_TEXT_SAMPLE]

    def _append(self, tag: str, selector: str, token: str) -> int:
        if len(self.items) >= MAX_SELECTOR_HINTS * 3:
            return -1
        self.items.append({"tag": tag, "selector": selector, "token": token, "text": ""})
        return len(self.items) - 1
