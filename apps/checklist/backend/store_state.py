"""P2 split aggregator for store_state."""

from __future__ import annotations

from store_state_crud import *  # noqa: F401,F403
from store_state_references import *  # noqa: F401,F403
from store_state_view import *  # noqa: F401,F403
import store_state_crud as _store_state_crud
import store_state_references as _store_state_references
import store_state_view as _store_state_view

_modules = (_store_state_crud, _store_state_references, _store_state_view,)
for _module in _modules:
    globals().update({name: value for name, value in _module.__dict__.items() if not name.startswith("__")})
for _module in _modules:
    _module.__dict__.update(globals())


def __getattr__(name: str):
    for _module in _modules:
        if name in _module.__dict__:
            return _module.__dict__[name]
    raise AttributeError(name)
