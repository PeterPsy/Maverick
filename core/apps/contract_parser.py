"""App contract parser implementation facade."""

from __future__ import annotations

from core.apps.contract_parser_impl import *  # noqa: F401,F403
from core.apps.contract_parser_impl import __dict__ as _impl_dict


def __getattr__(name: str):
    try:
        return _impl_dict[name]
    except KeyError as error:
        raise AttributeError(name) from error
