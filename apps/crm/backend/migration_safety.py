"""Preserve a consistent pre-migration SQLite backup; reject future schemas."""

from pathlib import Path
import sqlite3
from uuid import uuid4

from errors import ValidationError


def prepare_migration(db, root: Path, target_version: str):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'schema_metadata'").fetchone():
        return
    row = db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
    if not row:
        raise ValidationError("Existing CRM schema has no version; refusing an unverified migration.")
    try:
        version = int(row[0])
    except (TypeError, ValueError) as error:
        raise ValidationError("Invalid CRM schema version.") from error
    if version > int(target_version):
        raise ValidationError("CRM database is newer than this app; downgrade refused.")
    if version == int(target_version):
        return
    backup_dir = root / "backups"
    backup_dir.mkdir(exist_ok=True)
    path = backup_dir / f"schema-{version}-before-{target_version}-{uuid4().hex}.sqlite"
    destination = sqlite3.connect(path)
    try:
        db.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValidationError("Pre-migration backup failed integrity validation.")
    finally:
        destination.close()
