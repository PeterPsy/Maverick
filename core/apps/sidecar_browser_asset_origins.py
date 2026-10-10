"""Exact HTTPS origins for browser-loaded sidecar styles and fonts."""

import re
from typing import Any
from urllib.parse import urlsplit

from core.apps.contract_validation import _expect_string_list
from core.apps.errors import AppContractValidationError


_HTTPS_ORIGIN = re.compile(
    r"https://(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?::[0-9]{1,5})?"
)


def parse_browser_asset_origins(payload: dict[str, Any], field: str, *, label: str) -> list[str]:
    """Accept bounded exact origins, without paths, wildcards or CSP syntax."""
    origins = _expect_string_list(payload, field) if field in payload else []
    if len(origins) > 8 or len(set(origins)) != len(origins):
        raise AppContractValidationError(f"`{label}.{field}` requires at most 8 distinct HTTPS origins.")
    for origin in origins:
        if len(origin) > 512 or not _HTTPS_ORIGIN.fullmatch(origin):
            raise AppContractValidationError(f"`{label}.{field}` requires exact HTTPS origins.")
        try:
            port = urlsplit(origin).port
        except ValueError as error:
            raise AppContractValidationError(f"`{label}.{field}` contains an invalid port.") from error
        if port is not None and not 1 <= port <= 65535:
            raise AppContractValidationError(f"`{label}.{field}` contains an invalid port.")
    return origins
