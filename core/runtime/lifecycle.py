"""Runtime lifecycle service implementation facade."""

from __future__ import annotations

from core.runtime.lifecycle_service import *  # noqa: F401,F403
from core.runtime.lifecycle_service import __dict__ as _impl_dict


def __getattr__(name: str):
    try:
        return _impl_dict[name]
    except KeyError as error:
        raise AttributeError(name) from error
