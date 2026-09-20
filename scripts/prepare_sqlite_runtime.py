#!/usr/bin/env python3
"""Build a pinned, WAL-reset-safe SQLite shared library for a local Python deployment.

Does not change the system library or restart services. Select the printed library
directory with LD_LIBRARY_PATH for the backend, CLI and their app subprocesses.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import zipfile

VERSION = '3.51.3'
SOURCE_SHA3 = '32d5424f97e0a7fc5ed2f6335afbb58be4e0298bd7117a34e39d345ff13d859e'
SOURCE_URL = 'https://www.sqlite.org/2026/sqlite-amalgamation-3510300.zip'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    args = parser.parse_args()
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
        archive = response.read(16 * 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix='maverick-sqlite-build-') as scratch:
        root = Path(scratch)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            source = bundle.read('sqlite-amalgamation-3510300/sqlite3.c')
        if hashlib.sha3_256(source).hexdigest() != SOURCE_SHA3:
            raise SystemExit('SQLite source digest does not match the official release.')
        (root / 'sqlite3.c').write_bytes(source)
        subprocess.run([
            'cc', '-O2', '-fPIC', '-shared', '-DSQLITE_THREADSAFE=1',
            '-DSQLITE_ENABLE_FTS5', '-DSQLITE_ENABLE_COLUMN_METADATA',
            '-Wl,-soname,libsqlite3.so.0', '-o', str(root / 'libsqlite3.so.0'),
            str(root / 'sqlite3.c'), '-lpthread', '-ldl', '-lm',
        ], check=True)
        lib = args.prefix.resolve() / 'lib'
        lib.mkdir(parents=True, exist_ok=True)
        target = lib / 'libsqlite3.so.0'
        if target.exists():
            raise SystemExit('Refusing to replace an existing runtime library; use a new prefix.')
        target.write_bytes((root / 'libsqlite3.so.0').read_bytes())
        target.chmod(0o755)
    print(json.dumps({'version': VERSION, 'source_sha3_256': SOURCE_SHA3, 'library_directory': str(lib)}))


if __name__ == '__main__':
    main()
