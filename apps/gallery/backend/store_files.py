"""P2 split aggregator for store_files."""

from __future__ import annotations

from store_files_view import *  # noqa: F401,F403
from store_files_paths import *  # noqa: F401,F403
from store_files_records import *  # noqa: F401,F403
from store_files_content import *  # noqa: F401,F403
import store_files_view as _store_files_view
import store_files_paths as _store_files_paths
import store_files_records as _store_files_records
import store_files_content as _store_files_content

_modules = (_store_files_view, _store_files_paths, _store_files_records, _store_files_content,)
for _module in _modules:
    globals().update({name: value for name, value in _module.__dict__.items() if not name.startswith("__")})
for _module in _modules:
    _module.__dict__.update(globals())


def __getattr__(name: str):
    for _module in _modules:
        if name in _module.__dict__:
            return _module.__dict__[name]
    raise AttributeError(name)
