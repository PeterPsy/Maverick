"""P2 split aggregator for turn_submission_service."""

from __future__ import annotations

from core.runtime.app_references import *  # noqa: F401,F403
from core.runtime.turn_submission_service_events import *  # noqa: F401,F403
from core.runtime.turn_submission_service_output import *  # noqa: F401,F403
from core.runtime.turn_submission_service_runtime import *  # noqa: F401,F403
from core.runtime.turn_submission_service_submit import *  # noqa: F401,F403
from core.runtime import app_references as _app_references
from core.runtime import turn_submission_service_events as _turn_submission_service_events
from core.runtime import turn_submission_service_output as _turn_submission_service_output
from core.runtime import turn_submission_service_runtime as _turn_submission_service_runtime
from core.runtime import turn_submission_service_submit as _turn_submission_service_submit

_modules = (
    _app_references,
    _turn_submission_service_events,
    _turn_submission_service_output,
    _turn_submission_service_runtime,
    _turn_submission_service_submit,
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
