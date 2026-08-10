CREATE TABLE project_projections (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    projection_json TEXT NOT NULL CHECK (json_valid(projection_json)),
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE project_revision_navigation (
    project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
    branch_name TEXT NOT NULL DEFAULT 'main',
    undo_stack_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(undo_stack_json)),
    redo_stack_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(redo_stack_json)),
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, branch_name)
) STRICT;

CREATE TABLE project_operation_batches (
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    operation_batch_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    base_revision_id TEXT NOT NULL REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    request_digest TEXT NOT NULL,
    result_revision_id TEXT NOT NULL REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, operation_batch_id)
) STRICT;

CREATE TABLE project_autosaves (
    autosave_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    operation_batch_id TEXT NOT NULL,
    revision_id TEXT NOT NULL REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    UNIQUE (project_id, operation_batch_id)
) STRICT;

CREATE TABLE project_outbox (
    event_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    revision_id TEXT REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    resource TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'dispatched')),
    created_at TEXT NOT NULL,
    dispatched_at TEXT
) STRICT;

CREATE INDEX idx_project_operation_batches_revision
    ON project_operation_batches(project_id, result_revision_id);
CREATE INDEX idx_project_autosaves_project_created
    ON project_autosaves(project_id, created_at DESC);
CREATE INDEX idx_project_outbox_pending
    ON project_outbox(state, created_at, event_id);

UPDATE app_metadata
SET value = '2', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE key = 'schema_version';
