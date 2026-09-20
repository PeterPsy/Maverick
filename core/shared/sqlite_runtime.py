"""Runtime prerequisite shared by the two local, explicitly migrated SQLite owners."""

import sqlite3


MINIMUM_WAL_VERSION = (3, 51, 3)


def require_safe_wal_runtime() -> None:
    """Refuse concurrent WAL on versions lacking the upstream WAL-reset fix."""
    if sqlite3.sqlite_version_info < MINIMUM_WAL_VERSION:
        raise RuntimeError(
            'SQLite WAL requires runtime 3.51.3 or newer; '
            f'this Python process loads {sqlite3.sqlite_version}. '
            'Update the library used by backend, CLI and app processes before cutover.'
        )
