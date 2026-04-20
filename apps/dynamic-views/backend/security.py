"""Source validation for Dynamic Views packages."""

from __future__ import annotations

from errors import DynamicViewsValidationError


MAX_SOURCE_CHARS = 120_000
BLOCKED_HTML_SNIPPETS = (
    "<script src=",
    "<iframe",
)
BLOCKED_JS_SNIPPETS = (
    "import(",
    "fetch(",
    "xmlhttprequest",
    "websocket(",
    "document.cookie",
    "localstorage",
    "sessionstorage",
    "window.parent",
    "window.top",
    "window.opener",
)


def validate_dynamic_view_package_source(*, html: str, css: str, javascript: str) -> dict:
    normalized_html = str(html or "")
    normalized_css = str(css or "")
    normalized_javascript = str(javascript or "")

    if not normalized_html.strip():
        raise DynamicViewsValidationError("Dynamic view HTML cannot be empty.")
    if len(normalized_html) + len(normalized_css) + len(normalized_javascript) > MAX_SOURCE_CHARS:
        raise DynamicViewsValidationError("Dynamic view source exceeds the maximum allowed size.")

    html_probe = normalized_html.lower()
    for snippet in BLOCKED_HTML_SNIPPETS:
        if snippet in html_probe:
            raise DynamicViewsValidationError(f"Dynamic view HTML contains a blocked construct: {snippet}")

    js_probe = normalized_javascript.lower()
    for snippet in BLOCKED_JS_SNIPPETS:
        if snippet in js_probe:
            raise DynamicViewsValidationError(f"Dynamic view JavaScript contains a blocked construct: {snippet}")

    return {
        "status": "approved",
        "checks": [
            "no_external_script_src",
            "no_nested_iframe",
            "no_network_apis",
            "no_parent_window_access",
            "no_storage_access",
            "no_cookie_access",
            "size_limit_ok",
        ],
    }

