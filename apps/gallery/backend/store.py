"""Gallery file store implementation facade."""

from __future__ import annotations

from store_files import *  # noqa: F401,F403
from store_files import __dict__ as _impl_dict


def __getattr__(name: str):
    try:
        return _impl_dict[name]
    except KeyError as error:
        raise AttributeError(name) from error
