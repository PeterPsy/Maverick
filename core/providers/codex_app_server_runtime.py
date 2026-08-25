"""P2 split aggregator for codex_app_server_runtime."""

from __future__ import annotations

from core.providers.codex_app_server_runtime_errors import *  # noqa: F401,F403
from core.providers.codex_app_server_runtime_transport import *  # noqa: F401,F403
from core.providers.codex_app_server_runtime_process import *  # noqa: F401,F403
from core.providers.codex_app_server_runtime_lifecycle import *  # noqa: F401,F403
from core.providers.codex_app_server_runtime_thread import *  # noqa: F401,F403
from core.providers.codex_app_server_runtime_steering import *  # noqa: F401,F403
from core.providers.codex_app_server_runtime_protocol import *  # noqa: F401,F403
from core.providers.codex_app_server_runtime_notifications import *  # noqa: F401,F403
from core.providers import codex_app_server_runtime_errors as _codex_app_server_runtime_errors
from core.providers import codex_app_server_runtime_transport as _codex_app_server_runtime_transport
from core.providers import codex_app_server_runtime_process as _codex_app_server_runtime_process
from core.providers import codex_app_server_runtime_lifecycle as _codex_app_server_runtime_lifecycle
from core.providers import codex_app_server_runtime_thread as _codex_app_server_runtime_thread
from core.providers import codex_app_server_runtime_steering as _codex_app_server_runtime_steering
from core.providers import codex_app_server_runtime_protocol as _codex_app_server_runtime_protocol
from core.providers import codex_app_server_runtime_notifications as _codex_app_server_runtime_notifications

_modules = (
    _codex_app_server_runtime_errors,
    _codex_app_server_runtime_transport,
    _codex_app_server_runtime_process,
    _codex_app_server_runtime_lifecycle,
    _codex_app_server_runtime_thread,
    _codex_app_server_runtime_steering,
    _codex_app_server_runtime_protocol,
    _codex_app_server_runtime_notifications,
)
for _module in _modules:
    globals().update({name: value for name, value in _module.__dict__.items() if not name.startswith("__")})
for _module in _modules:
    _module.__dict__.update(
        {name: value for name, value in globals().items() if not name.startswith("__")}
    )


def __getattr__(name: str):
    for _module in _modules:
        if name in _module.__dict__:
            return _module.__dict__[name]
    raise AttributeError(name)
