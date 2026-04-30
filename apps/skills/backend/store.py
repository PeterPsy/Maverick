"""Skills store implementation facade."""

from __future__ import annotations

from store_skills import *  # noqa: F401,F403
from store_skills import __dict__ as _impl_dict


def __getattr__(name: str):
    try:
        return _impl_dict[name]
    except KeyError as error:
        raise AttributeError(name) from error
