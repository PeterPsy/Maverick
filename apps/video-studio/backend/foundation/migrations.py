"""Versioned, transactional SQLite migrations for Video Studio."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import sqlite3


_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Raised when migration discovery or application is unsafe."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    sql: str


def discover_migrations(migrations_root: Path) -> list[Migration]:
    """Load ordered migration files and reject ambiguous version history."""
    if migrations_root.is_symlink() or not migrations_root.is_dir():
        raise MigrationError("Video Studio migration source directory is missing.")
    migrations: list[Migration] = []
    versions: set[int] = set()
    for path in sorted(migrations_root.glob("*.sql")):
        if path.is_symlink():
            raise MigrationError(f"Migration `{path.name}` must not be a symbolic link.")
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"Unsupported migration filename `{path.name}`.")
        version = int(match.group("version"))
        if version <= 0 or version in versions:
            raise MigrationError(f"Duplicate or invalid migration version `{version}`.")
        versions.add(version)
        try:
            sql = path.read_text(encoding="utf-8")
        except OSError as error:
            raise MigrationError(f"Migration `{path.name}` could not be read.") from error
        if not sql.strip():
            raise MigrationError(f"Migration `{path.name}` is empty.")
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )
    if not migrations:
        raise MigrationError("Video Studio has no database migrations.")
    expected = list(range(1, migrations[-1].version + 1))
    actual = [migration.version for migration in migrations]
    if actual != expected:
        raise MigrationError("Video Studio migration versions must be contiguous from 1.")
    return migrations


def apply_migrations(connection: sqlite3.Connection, migrations: list[Migration]) -> list[int]:
    """Apply pending migrations atomically and verify immutable checksums."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        ) STRICT
        """
    )
    connection.commit()
    known_versions = {migration.version for migration in migrations}
    applied_versions = {
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
    }
    unknown_versions = sorted(applied_versions - known_versions)
    if unknown_versions:
        raise MigrationError(
            "Database contains migration versions unavailable in this app source: "
            + ", ".join(str(version) for version in unknown_versions)
            + "."
        )
    applied_now: list[int] = []
    for migration in migrations:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute(
                "SELECT name, checksum FROM schema_migrations WHERE version = ?",
                (migration.version,),
            ).fetchone()
            if existing_row is not None:
                existing = (str(existing_row[0]), str(existing_row[1]))
                if existing != (migration.name, migration.checksum):
                    raise MigrationError(
                        f"Applied migration {migration.version} does not match the source checksum."
                    )
                connection.commit()
                continue
            for statement in _migration_statements(migration.sql):
                if _first_sql_keyword(statement) in {
                    "BEGIN",
                    "COMMIT",
                    "END",
                    "ROLLBACK",
                    "SAVEPOINT",
                    "RELEASE",
                }:
                    raise MigrationError(
                        f"Migration {migration.version} contains transaction control."
                    )
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum, applied_at)
                VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (migration.version, migration.name, migration.checksum),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        except MigrationError:
            connection.rollback()
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise MigrationError(f"Migration {migration.version} failed: {error}") from error
        applied_now.append(migration.version)
    return applied_now


def _migration_statements(sql: str) -> list[str]:
    """Split trusted migration text without losing trigger or quoted semicolons."""
    statements: list[str] = []
    buffer: list[str] = []
    for character in sql:
        buffer.append(character)
        if character != ";":
            continue
        candidate = "".join(buffer).strip()
        if sqlite3.complete_statement(candidate):
            statements.append(candidate)
            buffer.clear()
    remainder = "".join(buffer).strip()
    if remainder:
        raise MigrationError("Migration SQL must terminate every statement with a semicolon.")
    if not statements:
        raise MigrationError("Migration SQL contains no executable statements.")
    return statements


def _first_sql_keyword(statement: str) -> str:
    """Return the leading keyword after SQL whitespace and comments."""
    offset = 0
    length = len(statement)
    while offset < length:
        while offset < length and statement[offset].isspace():
            offset += 1
        if statement.startswith("--", offset):
            newline = statement.find("\n", offset + 2)
            if newline < 0:
                return ""
            offset = newline + 1
            continue
        if statement.startswith("/*", offset):
            closing = statement.find("*/", offset + 2)
            if closing < 0:
                return ""
            offset = closing + 2
            continue
        break
    match = re.match(r"[A-Za-z]+", statement[offset:])
    return match.group(0).upper() if match else ""
