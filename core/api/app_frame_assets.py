"""Public static-asset URL handling for isolated app-frame documents."""

from __future__ import annotations

import re


_PUBLIC_APP_ASSET_ATTRIBUTE = re.compile(
    r"(?P<prefix>\b(?:src|href)\s*=\s*)(?P<quote>[\"'])(?P<path>/apps/[^/\"'<>\s]+/assets/[^\"'<>\s]+)(?P=quote)",
    flags=re.IGNORECASE,
)


def rewrite_public_app_asset_urls(html: str, platform_origin: str) -> str:
    """Route built app assets through Core's cacheable public platform origin."""

    return _PUBLIC_APP_ASSET_ATTRIBUTE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{platform_origin}{match.group('path')}{match.group('quote')}"
        ),
        html,
    )
