"""P2 split aggregator for lifecycle_service."""

from __future__ import annotations

from core.runtime.lifecycle_service_events import *  # noqa: F401,F403
from core.runtime.lifecycle_service_sessions import *  # noqa: F401,F403
from core.runtime.lifecycle_service_children import *  # noqa: F401,F403
from core.runtime.lifecycle_service_turns import *  # noqa: F401,F403
from core.runtime import lifecycle_service_sessions as _lifecycle_service_sessions
from core.runtime import lifecycle_service_children as _lifecycle_service_children
from core.runtime import lifecycle_service_turns as _lifecycle_service_turns
from core.runtime import lifecycle_service_events as _lifecycle_service_events

_modules = (
    _lifecycle_service_events,
    _lifecycle_service_sessions,
    _lifecycle_service_children,
    _lifecycle_service_turns,
)
for _module in _modules:
    globals().update({name: value for name, value in _module.__dict__.items() if not name.startswith("__")})
for _module in _modules:
    _module.__dict__.update(globals())


def __getattr__(name: str):
    for _module in _modules:
        if name in _module.__dict__:
            return _module.__dict__[name]
    raise AttributeError(name)
