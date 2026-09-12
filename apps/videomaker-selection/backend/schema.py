"""SQLite schema and connection ownership for Videomaker Selection."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from candidate_links import extract_instagram_profiles, extract_urls

SCHEMA_VERSION = "2"
DATABASE_NAME = "app.db"


def utcnow() -> str:
    return datetime.now(tz=UTC).isoformat()


def database_path(data_root: Path) -> Path:
    return Path(data_root) / DATABASE_NAME


@contextmanager
def connect(data_root: Path) -> Iterator[sqlite3.Connection]:
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path(root), timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 20000")
    initialize_schema(connection)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(data_root: Path) -> Path:
    with connect(data_root):
        pass
    return database_path(Path(data_root))


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidates (
          id TEXT PRIMARY KEY,
          source_response_number INTEGER,
          source_submitted_at TEXT NOT NULL DEFAULT '',
          name TEXT NOT NULL,
          email TEXT NOT NULL DEFAULT '',
          city TEXT NOT NULL DEFAULT '',
          bio TEXT NOT NULL DEFAULT '',
          work_status TEXT NOT NULL DEFAULT '',
          has_vat INTEGER NOT NULL DEFAULT 0,
          profile_code TEXT NOT NULL DEFAULT '',
          profile_label TEXT NOT NULL DEFAULT '',
          profile_answer TEXT NOT NULL DEFAULT '',
          traits_json TEXT NOT NULL DEFAULT '[]',
          social_usage TEXT NOT NULL DEFAULT '',
          autonomy TEXT NOT NULL DEFAULT '',
          workflow TEXT NOT NULL DEFAULT '',
          platforms_json TEXT NOT NULL DEFAULT '[]',
          opportunity TEXT NOT NULL DEFAULT '',
          capacity TEXT NOT NULL DEFAULT '',
          price_proposal TEXT NOT NULL DEFAULT '',
          portfolio_url TEXT NOT NULL DEFAULT '',
          portfolio_links_json TEXT NOT NULL DEFAULT '[]',
          instagram_links_json TEXT NOT NULL DEFAULT '[]',
          test_url TEXT NOT NULL DEFAULT '',
          additional_info TEXT NOT NULL DEFAULT '',
          duplicate_submissions_json TEXT NOT NULL DEFAULT '[]',
          privacy_accepted INTEGER NOT NULL DEFAULT 0,
          reviewed INTEGER NOT NULL DEFAULT 0,
          review_rank INTEGER,
          annotation TEXT NOT NULL DEFAULT '',
          specialty TEXT NOT NULL DEFAULT '',
          score_portfolio REAL,
          score_budget REAL,
          score_test REAL,
          review_score REAL,
          form_fit_score REAL,
          summary TEXT NOT NULL DEFAULT '',
          decision TEXT NOT NULL DEFAULT 'da_valutare',
          email_status TEXT NOT NULL DEFAULT 'da_contattare',
          call_status TEXT NOT NULL DEFAULT 'non_prevista',
          poc_status TEXT NOT NULL DEFAULT 'non_previsto',
          next_action TEXT NOT NULL DEFAULT '',
          next_action_due TEXT NOT NULL DEFAULT '',
          process_notes TEXT NOT NULL DEFAULT '',
          favorite INTEGER NOT NULL DEFAULT 0,
          archived INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS candidate_email_unique
          ON candidates(lower(email)) WHERE email <> '';
        CREATE INDEX IF NOT EXISTS candidate_pipeline_idx
          ON candidates(archived, decision, email_status, call_status, poc_status);
        CREATE INDEX IF NOT EXISTS candidate_scores_idx
          ON candidates(reviewed, review_score DESC, form_fit_score DESC);

        CREATE TABLE IF NOT EXISTS activities (
          id TEXT PRIMARY KEY,
          candidate_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          summary TEXT NOT NULL,
          details_json TEXT NOT NULL DEFAULT '{}',
          occurred_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS activity_candidate_idx
          ON activities(candidate_id, occurred_at DESC);

        CREATE TABLE IF NOT EXISTS app_state (
          key TEXT PRIMARY KEY,
          value_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """
    )
    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(candidates)").fetchall()}
    for column, definition in {
        "profile_answer": "TEXT NOT NULL DEFAULT ''",
        "workflow": "TEXT NOT NULL DEFAULT ''",
        "privacy_accepted": "INTEGER NOT NULL DEFAULT 0",
        "review_rank": "INTEGER",
        "portfolio_links_json": "TEXT NOT NULL DEFAULT '[]'",
        "instagram_links_json": "TEXT NOT NULL DEFAULT '[]'",
    }.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE candidates ADD COLUMN {column} {definition}")
    _backfill_candidate_links(connection)
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SCHEMA_VERSION,),
    )


def _backfill_candidate_links(connection: sqlite3.Connection) -> None:
    marker = connection.execute(
        "SELECT value FROM metadata WHERE key='candidate_links_backfill_version'"
    ).fetchone()
    if marker is not None and marker[0] == "1":
        return
    rows = connection.execute(
        "SELECT id, portfolio_url, bio, profile_answer, social_usage, workflow, opportunity, "
        "additional_info, portfolio_links_json, instagram_links_json FROM candidates"
    ).fetchall()
    for row in rows:
        portfolio_links = extract_urls(row["portfolio_url"])
        instagram_links = extract_instagram_profiles(
            row["portfolio_url"], row["bio"], row["profile_answer"], row["social_usage"],
            row["workflow"], row["opportunity"], row["additional_info"],
        )
        connection.execute(
            "UPDATE candidates SET portfolio_links_json=?, instagram_links_json=? WHERE id=?",
            (
                json.dumps(portfolio_links, ensure_ascii=False),
                json.dumps(instagram_links, ensure_ascii=False),
                row["id"],
            ),
        )
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES('candidate_links_backfill_version', '1') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
