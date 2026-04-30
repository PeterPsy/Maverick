"""Codex provider runtime implementation facade."""

from __future__ import annotations

from core.providers.provider_codex_runtime import *  # noqa: F401,F403
from core.providers.provider_codex_runtime import __dict__ as _impl_dict


def __getattr__(name: str):
    try:
        return _impl_dict[name]
    except KeyError as error:
        raise AttributeError(name) from error
