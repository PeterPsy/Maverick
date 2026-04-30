"""App Store HTTP API implementation facade."""

from __future__ import annotations

from core.api.app_store_http import *  # noqa: F401,F403
from core.api.app_store_http import __dict__ as _impl_dict


def __getattr__(name: str):
    try:
        return _impl_dict[name]
    except KeyError as error:
        raise AttributeError(name) from error
