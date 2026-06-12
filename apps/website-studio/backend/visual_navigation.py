"""Visual navigation helpers for Website Studio."""

from __future__ import annotations

from html.parser import HTMLParser
import hashlib
import re


MAX_NAVIGATION_SECTIONS = 32
MAX_NAVIGATION_COMPONENTS = 18
MAX_COMPONENT_SOURCE_FILES = 8
MAX_LABEL_CHARS = 90

_SECTION_HINT_TAGS = {"main", "section", "article", "nav", "header", "footer"}
_HEADING_HINT_TAGS = {"h1", "h2", "h3"}
_NON_COMPONENT_TAGS = {"html", "head", "meta", "link", "script", "style", "noscript", "source"}
_INTERACTIVE_COMPONENT_TAGS = {"a", "button", "form", "input", "select", "textarea"}
_MEDIA_COMPONENT_TAGS = {"video", "img", "picture", "svg", "iframe"}
_BUILDER_COMPONENT_TOKENS = {
    "booking",
    "button",
    "btn",
    "card",
    "carousel",
    "contact",
    "cta",
    "form",
    "gallery",
    "hamburger",
    "header",
    "hero",
    "image",
    "logo",
    "map",
    "media",
    "menu",
    "modal",
    "nav",
    "slider",
    "tab",
    "video",
}
_LAYOUT_ONLY_TOKENS = {
    "col",
    "column",
    "combo",
    "container",
    "content",
    "grid",
    "horizontal",
    "line",
    "overlay",
    "row",
    "span",
    "text",
    "title",
    "vertical",
    "wrapper",
}


def visual_sections_from_html(
    html: object,
    *,
    route: str,
    page_id: str,
    source_files: list[str],
    last_report_id: str = "",
) -> list[dict[str, object]]:
    parser = _SectionParser(route=route, page_id=page_id, source_files=source_files, last_report_id=last_report_id)
    parser.feed(str(html or "")[:1_000_000])
    return parser.items[:MAX_NAVIGATION_SECTIONS]


def visual_sections_from_selector_hints(
    selector_hints: object,
    *,
    route: str,
    page_id: str,
    source_files: list[str],
    last_report_id: str = "",
    limit: int = MAX_NAVIGATION_SECTIONS,
) -> list[dict[str, object]]:
    """Promote browser-observed structural selectors into visual sections."""
    if not isinstance(selector_hints, list):
        return []
    sections: list[dict[str, object]] = []
    seen: set[str] = set()
    selector_counts: dict[str, int] = {}
    for raw_hint in selector_hints:
        if len(sections) >= limit:
            break
        if not isinstance(raw_hint, dict):
            continue
        tag = _compact(raw_hint.get("tag"), 40).lower()
        selector = _compact(raw_hint.get("selector"), 180)
        if not selector:
            continue
        selector_counts[selector] = selector_counts.get(selector, 0) + 1
        selector = _indexed_selector(selector, selector_counts[selector])
        text = _compact(raw_hint.get("text"), MAX_LABEL_CHARS)
        token = _compact(raw_hint.get("token"), MAX_LABEL_CHARS)
        level = _heading_level(tag)
        if tag in _SECTION_HINT_TAGS:
            label = _label_from_selector(selector) or text or token or _titleize_token(tag)
        elif level:
            if not text:
                continue
            label = text or token or _label_from_selector(selector)
        else:
            continue
        key = _semantic_section_key(label or selector)
        if not key or key in seen:
            continue
        seen.add(key)
        anchor = selector if selector.startswith("#") else ""
        sections.append(
            {
                "id": _stable_id("section", page_id, route, selector, anchor),
                "kind": "section",
                "route": route or "/",
                "page_id": page_id,
                "selector": selector,
                "anchor": anchor,
                "label": label or _label_from_selector(selector) or "Section",
                "level": level,
                "source_files": source_files[:MAX_COMPONENT_SOURCE_FILES],
                "confidence": "preview_report",
                "visibility": {"status": "observed", "source": "preview_report"},
                "bounds": None,
                "last_report_id": last_report_id,
            }
        )
    return sections


def component_candidates_from_selector_hints(
    selector_hints: object,
    *,
    route: str,
    page_id: str = "",
    last_report_id: str = "",
    limit: int = MAX_NAVIGATION_COMPONENTS,
) -> list[dict[str, object]]:
    if not isinstance(selector_hints, list):
        return []
    components: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_hint in enumerate(selector_hints):
        if len(components) >= limit:
            break
        if not isinstance(raw_hint, dict):
            continue
        selector = _compact(raw_hint.get("selector"), 180)
        tag = _compact(raw_hint.get("tag"), 40).lower()
        if not selector or selector in seen:
            continue
        if not _is_builder_component_hint(selector, tag, raw_hint):
            continue
        seen.add(selector)
        text = _compact(raw_hint.get("text"), MAX_LABEL_CHARS)
        token = _compact(raw_hint.get("token"), MAX_LABEL_CHARS)
        label = text or _label_from_selector(selector) or token or f"Component {len(components) + 1}"
        source_files = _clean_strings(raw_hint.get("source_files"), limit=MAX_COMPONENT_SOURCE_FILES)
        components.append(
            {
                "id": _stable_id("component", page_id, route, selector, token or str(index)),
                "kind": "component",
                "route": route or "/",
                "page_id": page_id,
                "selector": selector,
                "label": label,
                "source_files": source_files,
                "confidence": _compact(raw_hint.get("confidence"), 60) or "candidate",
                "visibility": {"status": "candidate", "source": "preview_report"},
                "bounds": None,
                "last_report_id": last_report_id,
                "tag": tag,
                "asset_id": _compact(raw_hint.get("asset_id"), 80),
                "asset_path": _compact(raw_hint.get("asset_path"), 180),
            }
        )
    return components


def component_matches_query(component: dict[str, object], query: str) -> bool:
    needle = query.strip().lower()
    if not needle:
        return True
    haystack = " ".join(
        [
            str(component.get("label") or ""),
            str(component.get("route") or ""),
            str(component.get("selector") or ""),
            " ".join(str(item) for item in component.get("source_files", []) if str(item).strip()),
        ]
    ).lower()
    return needle in haystack


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _clean_strings(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _compact(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _label_from_selector(selector: str) -> str:
    clean = selector.strip()
    if clean.startswith("#"):
        return _titleize_token(clean[1:])
    if clean.startswith("."):
        return _titleize_token(clean[1:])
    attr_match = re.search(r"\[(?:aria-label|data-testid|data-component|id)=['\"]?([^'\"\]]+)", clean)
    if attr_match:
        return _titleize_token(attr_match.group(1))
    return clean


def _heading_level(tag: str) -> int:
    if tag in _HEADING_HINT_TAGS:
        return int(tag[1])
    return 0


def _semantic_section_key(value: str) -> str:
    text = re.sub(r"\b(section|area|block)\b", " ", value.lower())
    return re.sub(r"[^a-z0-9]+", "", text)


def _indexed_selector(selector: str, count: int) -> str:
    clean = selector.strip()
    if count > 1 and clean.lower() in _HEADING_HINT_TAGS:
        return f"{clean}:nth-of-type({count})"
    return clean


def _selector_token(selector: str) -> str:
    clean = selector.strip()
    if clean.startswith((".", "#")):
        return clean[1:].split(":", 1)[0]
    attr_match = re.search(r"\[(?:aria-label|data-testid|data-component|id)=['\"]?([^'\"\]]+)", clean)
    return attr_match.group(1) if attr_match else ""


def _is_builder_component_hint(selector: str, tag: str, hint: dict[str, object]) -> bool:
    selector_lower = selector.lower()
    if tag in _NON_COMPONENT_TAGS or tag in _SECTION_HINT_TAGS or tag in _HEADING_HINT_TAGS or tag == "p":
        return False
    if selector_lower in {"a", "p", "span", "div", "h1", "h2", "h3"}:
        return False
    if re.fullmatch(r"[a-z0-9-]+\[(?:href|src|poster|data-src|data-bg)\]", selector_lower):
        return False
    token = _selector_token(selector).lower()
    text = _compact(hint.get("text"), MAX_LABEL_CHARS)
    if token and _is_layout_only_component_token(token, tag):
        return False
    if tag in _INTERACTIVE_COMPONENT_TAGS and token:
        return True
    if tag in _MEDIA_COMPONENT_TAGS and token:
        return True
    if token and any(marker in token for marker in _BUILDER_COMPONENT_TOKENS):
        return True
    return tag == "button" and bool(text)


def _is_layout_only_component_token(token: str, tag: str) -> bool:
    words = {word for word in re.split(r"[^a-z0-9]+", token) if word}
    if not words:
        return False
    if words & {"logo", "button", "btn", "cta", "hamburger", "nav", "menu", "form", "video", "image"}:
        return False
    if "background" in words and tag not in {"video", "img", "picture"}:
        return True
    if "arrow" in words or "gradient" in words or "icon" in words or "plus" in words:
        return True
    return bool(words & _LAYOUT_ONLY_TOKENS)


def _titleize_token(value: str) -> str:
    text = re.sub(r"[_-]+", " ", value).strip()
    return text[:1].upper() + text[1:] if text else ""


class _SectionParser(HTMLParser):
    def __init__(self, *, route: str, page_id: str, source_files: list[str], last_report_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.route = route or "/"
        self.page_id = page_id
        self.source_files = source_files[:MAX_COMPONENT_SOURCE_FILES]
        self.last_report_id = last_report_id
        self.items: list[dict[str, object]] = []
        self._text_targets: list[int] = []
        self._tag_counts: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.items) >= MAX_NAVIGATION_SECTIONS:
            return
        tag_name = tag.lower()
        attr_map = {name.lower(): value or "" for name, value in attrs}
        if tag_name in {"h1", "h2", "h3"}:
            selector = self._selector_for(tag_name, attr_map)
            index = self._append(
                kind="section",
                selector=selector,
                label=_compact(attr_map.get("aria-label") or attr_map.get("title"), MAX_LABEL_CHARS),
                level=int(tag_name[1]),
                anchor=f"#{attr_map.get('id')}" if attr_map.get("id") else "",
            )
            self._text_targets.append(index)
            return
        if tag_name in {"section", "article", "nav", "header", "footer"}:
            label = _compact(attr_map.get("aria-label") or attr_map.get("title") or attr_map.get("id"), MAX_LABEL_CHARS)
            if not label and not attr_map.get("id"):
                return
            self._append(
                kind="section",
                selector=self._selector_for(tag_name, attr_map),
                label=label or _titleize_token(tag_name),
                level=0,
                anchor=f"#{attr_map.get('id')}" if attr_map.get("id") else "",
            )
            return
        if tag_name == "a" and attr_map.get("href", "").startswith("#") and len(attr_map.get("href", "")) > 1:
            index = self._append(
                kind="anchor",
                selector=self._selector_for(tag_name, attr_map),
                label=_compact(attr_map.get("aria-label") or attr_map.get("title") or attr_map.get("href"), MAX_LABEL_CHARS),
                level=0,
                anchor=attr_map.get("href", ""),
            )
            self._text_targets.append(index)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"a", "h1", "h2", "h3"} and self._text_targets:
            self._text_targets.pop()

    def handle_data(self, data: str) -> None:
        text = _compact(data, MAX_LABEL_CHARS)
        if not text or not self._text_targets:
            return
        index = self._text_targets[-1]
        if 0 <= index < len(self.items) and not self.items[index].get("label"):
            self.items[index]["label"] = text

    def _selector_for(self, tag: str, attrs: dict[str, str]) -> str:
        if attrs.get("id"):
            return f"#{attrs['id']}"
        if attrs.get("data-testid"):
            return f"{tag}[data-testid=\"{attrs['data-testid']}\"]"
        if attrs.get("aria-label"):
            return f"{tag}[aria-label=\"{attrs['aria-label']}\"]"
        self._tag_counts[tag] = self._tag_counts.get(tag, 0) + 1
        count = self._tag_counts[tag]
        return tag if count == 1 else f"{tag}:nth-of-type({count})"

    def _append(self, *, kind: str, selector: str, label: str, level: int, anchor: str) -> int:
        item = {
            "id": _stable_id(kind, self.page_id, self.route, selector, anchor),
            "kind": kind,
            "route": self.route,
            "page_id": self.page_id,
            "selector": selector,
            "anchor": anchor,
            "label": label or _label_from_selector(selector) or kind,
            "level": level,
            "source_files": self.source_files,
            "confidence": "source_html",
            "visibility": {"status": "candidate", "source": "source_html"},
            "bounds": None,
            "last_report_id": self.last_report_id,
        }
        self.items.append(item)
        return len(self.items) - 1
