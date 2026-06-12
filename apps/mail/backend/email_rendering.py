"""Email body rendering and sanitization policy for Mail."""

from __future__ import annotations

from dataclasses import dataclass
import html
from html.parser import HTMLParser
import re


BODY_SOURCE_LIMIT = 250_000
RENDER_POLICY_VERSION = 2


GMAIL_SUPPORTED_CSS_PROPERTIES = frozenset(
    {
        "azimuth",
        "background",
        "background-blend-mode",
        "background-clip",
        "background-color",
        "background-image",
        "background-origin",
        "background-position",
        "background-repeat",
        "background-size",
        "border",
        "border-bottom",
        "border-bottom-color",
        "border-bottom-left-radius",
        "border-bottom-right-radius",
        "border-bottom-style",
        "border-bottom-width",
        "border-collapse",
        "border-color",
        "border-left",
        "border-left-color",
        "border-left-style",
        "border-left-width",
        "border-radius",
        "border-right",
        "border-right-color",
        "border-right-style",
        "border-right-width",
        "border-spacing",
        "border-style",
        "border-top",
        "border-top-color",
        "border-top-left-radius",
        "border-top-right-radius",
        "border-top-style",
        "border-top-width",
        "border-width",
        "box-sizing",
        "break-after",
        "break-before",
        "break-inside",
        "caption-side",
        "clear",
        "color",
        "column-count",
        "column-fill",
        "column-gap",
        "column-rule",
        "column-rule-color",
        "column-rule-style",
        "column-rule-width",
        "column-span",
        "column-width",
        "columns",
        "direction",
        "display",
        "elevation",
        "empty-cells",
        "float",
        "font",
        "font-family",
        "font-feature-settings",
        "font-kerning",
        "font-size",
        "font-size-adjust",
        "font-stretch",
        "font-style",
        "font-synthesis",
        "font-variant",
        "font-variant-alternates",
        "font-variant-caps",
        "font-variant-east-asian",
        "font-variant-ligatures",
        "font-variant-numeric",
        "font-weight",
        "height",
        "image-orientation",
        "image-resolution",
        "ime-mode",
        "isolation",
        "layout-flow",
        "layout-grid",
        "layout-grid-char",
        "layout-grid-char-spacing",
        "layout-grid-line",
        "layout-grid-mode",
        "layout-grid-type",
        "letter-spacing",
        "line-break",
        "line-height",
        "list-style",
        "list-style-position",
        "list-style-type",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "marker-offset",
        "max-height",
        "max-width",
        "min-height",
        "min-width",
        "mix-blend-mode",
        "object-fit",
        "object-position",
        "opacity",
        "outline",
        "outline-color",
        "outline-style",
        "outline-width",
        "overflow",
        "overflow-x",
        "overflow-y",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "page-break-after",
        "page-break-before",
        "page-break-inside",
        "pause",
        "pause-after",
        "pause-before",
        "pitch",
        "pitch-range",
        "quotes",
        "richness",
        "speak",
        "speak-header",
        "speak-numeral",
        "speak-punctuation",
        "speech-rate",
        "stress",
        "table-layout",
        "text-align",
        "text-align-last",
        "text-autospace",
        "text-combine-upright",
        "text-decoration",
        "text-decoration-color",
        "text-decoration-line",
        "text-decoration-skip",
        "text-decoration-style",
        "text-emphasis",
        "text-emphasis-color",
        "text-emphasis-style",
        "text-indent",
        "text-justify",
        "text-kashida-space",
        "text-orientation",
        "text-overflow",
        "text-transform",
        "text-underline-position",
        "unicode-bidi",
        "vertical-align",
        "voice-family",
        "white-space",
        "width",
        "word-break",
        "word-spacing",
        "word-wrap",
        "writing-mode",
        "zoom",
    }
)

GMAIL_SUPPORTED_MEDIA_TYPES = frozenset({"all", "screen"})
GMAIL_SUPPORTED_MEDIA_FEATURES = frozenset(
    {
        "min-width",
        "max-width",
        "min-device-width",
        "max-device-width",
        "orientation",
        "min-resolution",
        "max-resolution",
    }
)
GMAIL_SUPPORTED_MEDIA_KEYWORDS = frozenset({"and", "only"})


@dataclass(frozen=True)
class RenderedEmailBody:
    body_text: str
    body_html_original_bounded: str
    body_html_gmail_sanitized: str
    body_html_rendered: str
    body_render_mode: str
    body_preview: str
    body_truncated: bool
    render_policy: dict[str, object]

    @property
    def body_html_sanitized(self) -> str:
        return self.body_html_rendered


def render_email_body(
    plain_chunks: list[str],
    html_chunks: list[str],
    *,
    source_limit: int = BODY_SOURCE_LIMIT,
) -> RenderedEmailBody:
    """Render extracted MIME body chunks into Mail's persisted body fields."""

    body_text, text_truncated = _join_bounded(plain_chunks, "\n\n", source_limit)
    body_html, html_truncated = _join_bounded(html_chunks, "\n", source_limit)
    gmail_sanitized_html = sanitize_email_html(body_html) if body_html else ""
    rendered_html = gmail_sanitized_html
    if not body_text and rendered_html:
        body_text = html_to_text(rendered_html)
    body_preview = re.sub(r"\s+", " ", body_text).strip()[:240]
    return RenderedEmailBody(
        body_text=body_text,
        body_html_original_bounded=body_html,
        body_html_gmail_sanitized=gmail_sanitized_html,
        body_html_rendered=rendered_html,
        body_render_mode="html" if rendered_html else "plain",
        body_preview=body_preview,
        body_truncated=text_truncated or html_truncated,
        render_policy=_render_policy(source_limit, has_html=bool(body_html)),
    )


def sanitize_email_html(value: str) -> str:
    parser = _EmailHTMLSanitizer()
    parser.feed(value)
    parser.close()
    return parser.html


def html_to_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text


class _HTMLTextExtractor(HTMLParser):
    _block_end_tags = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}
    _skip_text_tags = {"style", "script", "noscript", "template", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._chunks: list[str] = []
        self._skip_depth = 0

    @property
    def text(self) -> str:
        return re.sub(r"[ \t\r\f\v]+", " ", html.unescape("".join(self._chunks))).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._skip_text_tags:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        self._chunks.append("\n" if tag == "br" else " ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth or tag in self._skip_text_tags:
            return
        self._chunks.append("\n" if tag == "br" else " ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._skip_text_tags and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        self._chunks.append("\n" if tag in self._block_end_tags else " ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self._chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self._chunks.append(f"&#{name};")


def truncate_sanitized_html(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    truncator = _SanitizedHTMLTruncator(max_chars)
    truncator.feed(value)
    truncator.close()
    return truncator.html


class _EmailHTMLSanitizer(HTMLParser):
    _allowed_tags = {
        "a",
        "b",
        "blockquote",
        "br",
        "caption",
        "center",
        "cite",
        "code",
        "col",
        "colgroup",
        "dd",
        "del",
        "div",
        "dl",
        "dt",
        "em",
        "font",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "li",
        "ol",
        "p",
        "pre",
        "q",
        "s",
        "small",
        "span",
        "strike",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "tt",
        "u",
        "ul",
        "wbr",
    }
    _void_tags = {"br", "col", "hr", "wbr"}
    _skip_tags = {"script", "iframe", "object", "embed", "form", "input", "button", "textarea", "select", "option"}
    _global_attrs = {
        "title",
        "role",
        "aria-label",
        "align",
        "bgcolor",
        "border",
        "cellpadding",
        "cellspacing",
        "char",
        "charoff",
        "color",
        "colspan",
        "dir",
        "face",
        "headers",
        "height",
        "lang",
        "nowrap",
        "rowspan",
        "scope",
        "size",
        "start",
        "summary",
        "type",
        "valign",
        "width",
    }
    _uri_attrs = {"href"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0
        self._style_depth = 0
        self._style_chunks: list[str] = []

    @property
    def html(self) -> str:
        return "".join(self._out).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._style_depth:
            return
        if tag == "style":
            if not self._skip_depth:
                self._style_depth += 1
                self._style_chunks = []
            return
        if tag in self._skip_tags:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "img":
            self._append_blocked_image(attrs)
            return
        if tag not in self._allowed_tags:
            return
        clean_attrs = self._clean_attrs(tag, attrs)
        suffix = "".join(f' {name}="{html.escape(value, quote=True)}"' for name, value in clean_attrs)
        self._out.append(f"<{tag}{suffix}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._void_tags and tag.lower() in self._allowed_tags:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "style" and self._style_depth:
            self._style_depth -= 1
            if not self._style_depth:
                css = _sanitize_css_block("".join(self._style_chunks))
                if css:
                    self._out.append(f"<style>{css}</style>")
                self._style_chunks = []
            return
        if tag in self._skip_tags and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth or tag not in self._allowed_tags or tag in self._void_tags:
            return
        self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._style_depth and not self._skip_depth:
            self._style_chunks.append(data)
            return
        if not self._skip_depth:
            self._out.append(html.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if self._style_depth and not self._skip_depth:
            self._style_chunks.append(f"&{name};")
            return
        if not self._skip_depth:
            self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._style_depth and not self._skip_depth:
            self._style_chunks.append(f"&#{name};")
            return
        if not self._skip_depth:
            self._out.append(f"&#{name};")

    def _clean_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
        clean: list[tuple[str, str]] = []
        background_image = ""
        for name, raw_value in attrs:
            attr = name.lower()
            value = str(raw_value or "").strip()
            if not value or attr.startswith("on"):
                continue
            if attr in self._uri_attrs and _safe_url(value):
                clean.append((attr, value))
                if tag == "a":
                    clean.extend([("target", "_blank"), ("rel", "noopener noreferrer")])
            elif attr == "style":
                style = _safe_style(value)
                if style:
                    clean.append((attr, style))
                background_image = background_image or _first_css_image_url(value)
            elif attr == "background":
                if _safe_remote_image_url(value):
                    background_image = background_image or value[:500]
            elif attr == "class":
                class_name = re.sub(r"[\x00-\x1f<>`]", "", value).strip()
                if class_name:
                    clean.append((attr, class_name[:1000]))
            elif attr == "id":
                element_id = re.sub(r"[\x00-\x1f<>`]", "", value).strip()
                if element_id:
                    clean.append((attr, element_id[:200]))
            elif attr in self._global_attrs or (attr.startswith("data-") and not _is_reserved_mail_data_attr(attr)):
                clean.append((attr, value[:500]))
        if background_image:
            clean.append(("data-mail-background-image", background_image[:500]))
        return clean

    def _append_blocked_image(self, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): str(value or "").strip() for name, value in attrs}
        src = attr_map.get("src", "")
        marker = "inline image" if src.lower().startswith("cid:") else "remote image"
        alt = attr_map.get("alt") or attr_map.get("title") or marker
        metadata = {
            "data-mail-image": src[:500],
            "data-mail-alt": alt[:120] or marker,
            "data-mail-width": attr_map.get("width", "")[:40],
            "data-mail-height": attr_map.get("height", "")[:40],
            "data-mail-style": _safe_style(attr_map.get("style", "")),
        }
        metadata_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in metadata.items()
            if value
        )
        self._out.append(
            '<span class="mail-blocked-image"'
            f"{metadata_attrs}>"
            f"{html.escape(alt[:120] or marker)}"
            "</span>"
        )


class _SanitizedHTMLTruncator(HTMLParser):
    _void_tags = {"br", "hr"}

    def __init__(self, text_chars: int) -> None:
        super().__init__(convert_charrefs=True)
        self.remaining = max(0, text_chars)
        self.out: list[str] = []
        self.open_tags: list[str] = []
        self.stopped = False

    @property
    def html(self) -> str:
        return "".join(self.out) + "".join(f"</{tag}>" for tag in reversed(self.open_tags))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.stopped:
            return
        tag = tag.lower()
        suffix = "".join(f' {name.lower()}="{html.escape(str(value or ""), quote=True)}"' for name, value in attrs)
        self.out.append(f"<{tag}{suffix}>")
        if tag not in self._void_tags:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.stopped:
            return
        tag = tag.lower()
        suffix = "".join(f' {name.lower()}="{html.escape(str(value or ""), quote=True)}"' for name, value in attrs)
        self.out.append(f"<{tag}{suffix}>")

    def handle_data(self, data: str) -> None:
        if self.stopped or not data:
            return
        if len(data) > self.remaining:
            self.out.append(html.escape(data[: self.remaining], quote=False))
            self.stopped = True
            return
        self.out.append(html.escape(data, quote=False))
        self.remaining -= len(data)

    def handle_endtag(self, tag: str) -> None:
        if self.stopped:
            return
        tag = tag.lower()
        for index in range(len(self.open_tags) - 1, -1, -1):
            if self.open_tags[index] == tag:
                del self.open_tags[index:]
                self.out.append(f"</{tag}>")
                break


def _join_bounded(chunks: list[str], separator: str, source_limit: int) -> tuple[str, bool]:
    value = separator.join(chunk for chunk in chunks if chunk).strip()
    return value[:source_limit], len(value) > source_limit


def _render_policy(source_limit: int, *, has_html: bool) -> dict[str, object]:
    return {
        "version": RENDER_POLICY_VERSION,
        "source_limit": source_limit,
        "source_html": "text/html" if has_html else "",
        "sanitizer": "mail-gmail-html-sanitizer",
        "css_policy": {
            "style_blocks": "sanitized",
            "inline_styles": "allowlisted",
            "resource_urls": "blocked",
        },
        "image_policy": {
            "cid": "placeholder_with_attachment_metadata",
            "remote": "blocked_placeholder",
            "background": "blocked_metadata",
        },
        "rendered_from": "body_html_gmail_sanitized" if has_html else "body_text",
    }


def _safe_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("https://", "http://", "mailto:"))


def _is_reserved_mail_data_attr(attr: str) -> bool:
    return attr == "data-mail" or attr.startswith("data-mail-")


def _safe_remote_image_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("https://", "http://"))


def _first_css_image_url(value: str) -> str:
    decoded = _decode_css_escapes(html.unescape(value))
    for match in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", decoded, flags=re.IGNORECASE):
        url = match.group(2).strip()
        if _safe_remote_image_url(url):
            return url
    return ""


def _strip_css_urls(value: str) -> str:
    return re.sub(r"url\(\s*(['\"]?).*?\1\s*\)", "", value, flags=re.IGNORECASE)


def _sanitize_css_block(value: str) -> str:
    css = _decode_css_escapes(html.unescape(value))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r"(?is)</?style[^>]*>", "", css)
    css = css.replace("<", "")
    return _sanitize_css_stylesheet(css).strip()[:50_000]


def _safe_style(value: str) -> str:
    decoded_value = _decode_css_escapes(value)
    if "<" in decoded_value:
        return ""
    return _sanitize_css_declarations(decoded_value, max_value_chars=240)[:4000]


def _sanitize_css_stylesheet(value: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(value):
        index = _skip_css_space(value, index)
        if index >= len(value):
            break
        if value[index] == "@":
            at_name_match = re.match(r"@([a-zA-Z-]+)", value[index:])
            at_name = at_name_match.group(1).lower() if at_name_match else ""
            if at_name == "media":
                brace = _find_next_top_level_char(value, "{", index)
                if brace < 0:
                    break
                end = _find_matching_brace(value, brace)
                if end < 0:
                    break
                media_query = _safe_media_query(value[index + len("@media") : brace])
                body = _sanitize_css_stylesheet(value[brace + 1 : end])
                if media_query and body:
                    out.append(f"@media {media_query} {{{body}}}")
                index = end + 1
                continue
            index = _skip_css_at_rule(value, index)
            continue

        brace = _find_next_top_level_char(value, "{", index)
        if brace < 0:
            break
        selector = _safe_css_selector(value[index:brace])
        end = _find_matching_brace(value, brace)
        if end < 0:
            break
        declarations = _sanitize_css_declarations(value[brace + 1 : end])
        if selector and declarations:
            out.append(f"{selector} {{ {declarations} }}")
        index = end + 1
    return " ".join(out)


def _sanitize_css_declarations(value: str, *, max_value_chars: int = 500) -> str:
    declarations = []
    for declaration in _split_css_declarations(value):
        if ":" not in declaration:
            continue
        name, raw = declaration.split(":", 1)
        prop = name.strip().lower()
        if prop not in GMAIL_SUPPORTED_CSS_PROPERTIES:
            continue
        if prop == "background-image" and _css_value_contains_url(raw):
            continue
        css_value = _safe_css_value(raw.strip())
        if css_value:
            declarations.append(f"{prop}: {css_value[:max_value_chars]}")
    return "; ".join(declarations)


def _safe_css_value(value: str) -> str:
    css_value = _strip_css_urls(_decode_css_escapes(value)).strip()
    lowered_value = css_value.lower()
    if any(blocked in lowered_value for blocked in ("url(", "expression(", "javascript:", "behavior:", "-moz-binding", "@import", "<")):
        return ""
    css_value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", css_value)
    return css_value


def _css_value_contains_url(value: str) -> bool:
    return "url(" in _decode_css_escapes(html.unescape(value)).lower()


def _split_css_declarations(value: str) -> list[str]:
    declarations: list[str] = []
    start = 0
    quote = ""
    paren_depth = 0
    for index, char in enumerate(value):
        if quote:
            if char == quote and (index == 0 or value[index - 1] != "\\"):
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "(":
            paren_depth += 1
            continue
        if char == ")" and paren_depth:
            paren_depth -= 1
            continue
        if char == ";" and not paren_depth:
            declarations.append(value[start:index])
            start = index + 1
    declarations.append(value[start:])
    return declarations


def _safe_css_selector(value: str) -> str:
    selector = " ".join(value.strip().split())
    if not selector or "@" in selector:
        return ""
    if any(blocked in selector.lower() for blocked in ("expression", "javascript:", "<", ">")):
        return ""
    if not re.fullmatch(r"[#.\w\s,:*>\-+~\[\]=\"'()|^$]+", selector):
        return ""
    return selector[:1000]


def _safe_media_query(value: str) -> str:
    query = " ".join(value.strip().split())
    if not query or any(blocked in query.lower() for blocked in (";", "{", "}", "<", ">", "expression", "javascript:")):
        return ""
    tokens = re.findall(r"[A-Za-z-]+", query.lower())
    for token in tokens:
        if token in GMAIL_SUPPORTED_MEDIA_TYPES or token in GMAIL_SUPPORTED_MEDIA_FEATURES or token in GMAIL_SUPPORTED_MEDIA_KEYWORDS:
            continue
        if token in {"px", "em", "rem", "dppx", "dpi", "dpcm", "portrait", "landscape"}:
            continue
        return ""
    if not re.fullmatch(r"[A-Za-z0-9\s:().,\-/%]+", query):
        return ""
    return query[:500]


def _skip_css_space(value: str, index: int) -> int:
    while index < len(value) and value[index].isspace():
        index += 1
    return index


def _find_next_top_level_char(value: str, target: str, start: int) -> int:
    quote = ""
    paren_depth = 0
    for index in range(start, len(value)):
        char = value[index]
        if quote:
            if char == quote and (index == 0 or value[index - 1] != "\\"):
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "(":
            paren_depth += 1
            continue
        if char == ")" and paren_depth:
            paren_depth -= 1
            continue
        if char == target and not paren_depth:
            return index
    return -1


def _find_matching_brace(value: str, open_index: int) -> int:
    quote = ""
    depth = 0
    for index in range(open_index, len(value)):
        char = value[index]
        if quote:
            if char == quote and (index == 0 or value[index - 1] != "\\"):
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _skip_css_at_rule(value: str, start: int) -> int:
    brace = _find_next_top_level_char(value, "{", start)
    semicolon = _find_next_top_level_char(value, ";", start)
    if semicolon >= 0 and (brace < 0 or semicolon < brace):
        return semicolon + 1
    if brace >= 0:
        end = _find_matching_brace(value, brace)
        return len(value) if end < 0 else end + 1
    return len(value)


def _decode_css_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        escaped = match.group(1)
        hex_value = escaped.strip()
        if re.fullmatch(r"[0-9a-fA-F]{1,6}", hex_value):
            try:
                return chr(int(hex_value, 16))
            except ValueError:
                return ""
        return escaped[:1]

    return re.sub(r"\\([0-9a-fA-F]{1,6}\s?|.)", replace, value)
