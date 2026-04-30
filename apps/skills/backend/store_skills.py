"""P2 split aggregator for store_skills."""

from __future__ import annotations

from store_skills_core import *  # noqa: F401,F403
from store_skills_view import *  # noqa: F401,F403
import store_skills_core as _store_skills_core
import store_skills_view as _store_skills_view

_modules = (_store_skills_core, _store_skills_view,)
for _module in _modules:
    globals().update({name: value for name, value in _module.__dict__.items() if not name.startswith("__")})
for _module in _modules:
    _module.__dict__.update(globals())


def __getattr__(name: str):
    for _module in _modules:
        if name in _module.__dict__:
            return _module.__dict__[name]
    raise AttributeError(name)
