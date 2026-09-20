import unittest
from unittest.mock import patch

from core.shared.sqlite_runtime import require_safe_wal_runtime


class SQLiteRuntimeTests(unittest.TestCase):
    def test_rejects_unpatched_runtime(self):
        with patch('sqlite3.sqlite_version_info', (3, 46, 1)):
            with self.assertRaisesRegex(RuntimeError, '3.51.3'):
                require_safe_wal_runtime()

    def test_accepts_fixed_and_newer_runtimes(self):
        for version in ((3, 51, 3), (3, 52, 1)):
            with self.subTest(version=version), patch('sqlite3.sqlite_version_info', version):
                require_safe_wal_runtime()
