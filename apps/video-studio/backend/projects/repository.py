"""SQLite repository for immutable project revisions and atomic projections."""

from __future__ import annotations

from contextlib import closing, contextmanager
import json
import sqlite3
from typing import Any, Iterator

from project_ir.canonical import canonical_dumps

from foundation.database import FoundationDatabase

from .errors import ProjectError, concurrency_conflict, not_found


class ProjectRepository:
    def __init__(self, database: FoundationDatabase) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_project(self, project_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        if connection is None:
            with closing(self.database.connect(read_only=True)) as reader:
                return self.get_project(project_id, reader)
        row = connection.execute(
            """
            SELECT p.project_id, p.name, p.description, p.created_at, p.updated_at,
                   p.archived_at, b.head_revision_id
            FROM projects p
            JOIN project_branches b ON b.project_id = p.project_id AND b.name = 'main'
            WHERE p.project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            raise not_found("project", project_id)
        return {
            "project_id": str(row[0]),
            "name": str(row[1]),
            "description": str(row[2]),
            "created_at": str(row[3]),
            "updated_at": str(row[4]),
            "archived_at": str(row[5]) if row[5] is not None else None,
            "head_revision_id": str(row[6]),
        }

    def list_projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        condition = "" if include_archived else "WHERE p.archived_at IS NULL"
        with closing(self.database.connect(read_only=True)) as connection:
            rows = connection.execute(
                f"""
                SELECT p.project_id, p.name, p.description, p.created_at, p.updated_at,
                       p.archived_at, b.head_revision_id
                FROM projects p
                JOIN project_branches b ON b.project_id = p.project_id AND b.name = 'main'
                {condition}
                ORDER BY p.updated_at DESC, p.project_id
                """
            ).fetchall()
        return [
            {
                "project_id": str(row[0]),
                "name": str(row[1]),
                "description": str(row[2]),
                "created_at": str(row[3]),
                "updated_at": str(row[4]),
                "archived_at": str(row[5]) if row[5] is not None else None,
                "head_revision_id": str(row[6]),
            }
            for row in rows
        ]

    def get_revision(
        self,
        project_id: str,
        revision_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        if connection is None:
            with closing(self.database.connect(read_only=True)) as reader:
                return self.get_revision(project_id, revision_id, reader)
        row = connection.execute(
            """
            SELECT revision_id, project_id, parent_revision_id, schema_version,
                   project_ir_json, operation_batch_json, author_kind, author_id,
                   digest, message, created_at
            FROM project_revisions WHERE project_id = ? AND revision_id = ?
            """,
            (project_id, revision_id),
        ).fetchone()
        if row is None:
            raise not_found("revision", revision_id)
        return {
            "revision_id": str(row[0]),
            "project_id": str(row[1]),
            "parent_revision_id": str(row[2]) if row[2] is not None else None,
            "schema_version": int(row[3]),
            "project_ir": json.loads(str(row[4])),
            "operation_batch": json.loads(str(row[5])),
            "actor": {"kind": str(row[6]), "id": str(row[7]) if row[7] is not None else ""},
            "digest": str(row[8]),
            "message": str(row[9]),
            "created_at": str(row[10]),
        }

    def idempotency_result(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        batch_id: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT request_digest, result_json FROM project_operation_batches
            WHERE project_id = ? AND operation_batch_id = ?
            """,
            (project_id, batch_id),
        ).fetchone()
        if row is None:
            return None
        if str(row[0]) != request_digest:
            raise ProjectError(
                "operation_batch_id_conflict",
                "Operation batch id was already used with different content.",
                path="/operation_batch_id",
                status_code=409,
            )
        return json.loads(str(row[1]))

    def insert_project(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        name: str,
        description: str,
        timestamp: str,
    ) -> None:
        try:
            connection.execute(
                """
                INSERT INTO projects(project_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, name, description, timestamp, timestamp),
            )
        except sqlite3.IntegrityError as error:
            raise ProjectError("project_exists", "Project id already exists.", status_code=409) from error

    def insert_revision(
        self,
        connection: sqlite3.Connection,
        *,
        revision_id: str,
        project_id: str,
        parent_revision_id: str | None,
        document: dict[str, Any],
        operation_batch: object,
        actor: dict[str, str],
        digest: str,
        message: str,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO project_revisions(
                revision_id, project_id, parent_revision_id, schema_version,
                project_ir_json, operation_batch_json, author_kind, author_id,
                digest, message, created_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                project_id,
                parent_revision_id,
                canonical_dumps(document),
                canonical_dumps(operation_batch),
                actor["kind"],
                actor["id"],
                digest,
                message,
                timestamp,
            ),
        )

    def initialize_head(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        revision_id: str,
        document: dict[str, Any],
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO project_branches(branch_id, project_id, name, head_revision_id, created_at, updated_at)
            VALUES (?, ?, 'main', ?, ?, ?)
            """,
            (f"branch-{project_id}-main", project_id, revision_id, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO project_revision_navigation(project_id, branch_name, undo_stack_json, redo_stack_json, updated_at)
            VALUES (?, 'main', '[]', '[]', ?)
            """,
            (project_id, timestamp),
        )
        self.write_projection(connection, project_id, revision_id, document, timestamp)

    def update_head(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        expected_revision_id: str,
        revision_id: str,
        document: dict[str, Any],
        timestamp: str,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE project_branches SET head_revision_id = ?, updated_at = ?
            WHERE project_id = ? AND name = 'main' AND head_revision_id = ?
            """,
            (revision_id, timestamp, project_id, expected_revision_id),
        )
        if cursor.rowcount != 1:
            raise concurrency_conflict()
        connection.execute(
            "UPDATE projects SET name = ?, updated_at = ? WHERE project_id = ?",
            (str(document["metadata"]["name"]), timestamp, project_id),
        )
        self.write_projection(connection, project_id, revision_id, document, timestamp)

    def write_projection(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        revision_id: str,
        document: dict[str, Any],
        timestamp: str,
    ) -> None:
        projection = {
            "asset_count": len(document.get("assets", [])),
            "duration_frames": document.get("duration_frames", 0),
            "name": document.get("metadata", {}).get("name", ""),
            "track_count": len(document.get("timeline", {}).get("tracks", [])),
        }
        connection.execute(
            """
            INSERT INTO project_projections(project_id, revision_id, projection_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
              revision_id = excluded.revision_id,
              projection_json = excluded.projection_json,
              updated_at = excluded.updated_at
            """,
            (project_id, revision_id, canonical_dumps(projection), timestamp),
        )

    def navigation(self, connection: sqlite3.Connection, project_id: str) -> tuple[list[str], list[str]]:
        row = connection.execute(
            "SELECT undo_stack_json, redo_stack_json FROM project_revision_navigation WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise ProjectError("navigation_missing", "Project navigation state is unavailable.", status_code=500)
        return json.loads(str(row[0])), json.loads(str(row[1]))

    def write_navigation(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        undo: list[str],
        redo: list[str],
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            UPDATE project_revision_navigation
            SET undo_stack_json = ?, redo_stack_json = ?, updated_at = ?
            WHERE project_id = ?
            """,
            (canonical_dumps(undo), canonical_dumps(redo), timestamp, project_id),
        )
