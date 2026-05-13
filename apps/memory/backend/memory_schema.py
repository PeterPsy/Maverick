"""SQLite schema statements for Memory."""

from __future__ import annotations


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nodes (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      title TEXT NOT NULL,
      summary TEXT NOT NULL DEFAULT '',
      body_text TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'active',
      importance REAL NOT NULL DEFAULT 0.5,
      confidence REAL NOT NULL DEFAULT 1.0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      deleted_at TEXT,
      deleted_by TEXT,
      delete_reason TEXT,
      last_accessed_at TEXT,
      metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS edges (
      id TEXT PRIMARY KEY,
      source_node_id TEXT NOT NULL,
      target_node_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      weight REAL NOT NULL DEFAULT 0.5,
      confidence REAL NOT NULL DEFAULT 1.0,
      reason TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      deleted_at TEXT,
      metadata_json TEXT NOT NULL DEFAULT '{}',
      FOREIGN KEY(source_node_id) REFERENCES nodes(id),
      FOREIGN KEY(target_node_id) REFERENCES nodes(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS external_refs (
      id TEXT PRIMARY KEY,
      node_id TEXT NOT NULL,
      ref_kind TEXT NOT NULL,
      owning_app_id TEXT NOT NULL DEFAULT '',
      entity_type TEXT NOT NULL DEFAULT '',
      entity_id TEXT NOT NULL DEFAULT '',
      file_id TEXT NOT NULL DEFAULT '',
      workspace_relative_path TEXT NOT NULL DEFAULT '',
      uri TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      metadata_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(node_id) REFERENCES nodes(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
      id TEXT PRIMARY KEY,
      node_id TEXT NOT NULL,
      external_ref_id TEXT,
      chunk_index INTEGER NOT NULL DEFAULT 0,
      content_text TEXT NOT NULL,
      content_hash TEXT NOT NULL DEFAULT '',
      token_count INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      metadata_json TEXT NOT NULL DEFAULT '{}',
      FOREIGN KEY(node_id) REFERENCES nodes(id),
      FOREIGN KEY(external_ref_id) REFERENCES external_refs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
      id TEXT PRIMARY KEY,
      event_type TEXT NOT NULL,
      actor_type TEXT NOT NULL DEFAULT '',
      actor_id TEXT NOT NULL DEFAULT '',
      node_id TEXT,
      edge_id TEXT,
      external_ref_id TEXT,
      payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS retrieval_feedback (
      id TEXT PRIMARY KEY,
      query TEXT NOT NULL,
      node_id TEXT,
      edge_id TEXT,
      feedback_kind TEXT NOT NULL,
      actor_type TEXT NOT NULL DEFAULT '',
      actor_id TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_jobs (
      id TEXT PRIMARY KEY,
      job_type TEXT NOT NULL,
      status TEXT NOT NULL,
      target_kind TEXT NOT NULL,
      target_id TEXT NOT NULL,
      attempt_count INTEGER NOT NULL DEFAULT 0,
      last_error TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
      node_id UNINDEXED,
      title,
      summary,
      body_text
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_nodes_type_status ON nodes(type, status)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_updated ON nodes(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind, status)",
    "CREATE INDEX IF NOT EXISTS idx_external_refs_app_entity ON external_refs(owning_app_id, entity_type, entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_external_refs_file ON external_refs(file_id, workspace_relative_path)",
)
