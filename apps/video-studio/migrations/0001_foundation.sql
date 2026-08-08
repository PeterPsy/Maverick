CREATE TABLE app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

INSERT INTO app_metadata(key, value) VALUES ('schema_version', '1');

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
) STRICT;

CREATE TABLE media_assets (
    media_asset_id TEXT PRIMARY KEY,
    storage_file_id TEXT NOT NULL,
    source_version TEXT NOT NULL DEFAULT '',
    content_sha256 TEXT,
    media_kind TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    duration_us INTEGER CHECK (duration_us IS NULL OR duration_us >= 0),
    width INTEGER CHECK (width IS NULL OR width > 0),
    height INTEGER CHECK (height IS NULL OR height > 0),
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (storage_file_id, source_version)
) STRICT;

CREATE TABLE project_revisions (
    revision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    parent_revision_id TEXT REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    project_ir_json TEXT NOT NULL CHECK (json_valid(project_ir_json)),
    operation_batch_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(operation_batch_json)),
    author_kind TEXT NOT NULL,
    author_id TEXT,
    edit_session_id TEXT REFERENCES edit_sessions(edit_session_id) ON DELETE SET NULL,
    digest TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (project_id, digest)
) STRICT;

CREATE TABLE project_branches (
    branch_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    head_revision_id TEXT REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, name)
) STRICT;

CREATE TABLE project_assets (
    project_asset_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE RESTRICT,
    added_revision_id TEXT REFERENCES project_revisions(revision_id) ON DELETE SET NULL,
    role TEXT NOT NULL DEFAULT 'source',
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (project_id, media_asset_id)
) STRICT;

CREATE TABLE media_derivatives (
    derivative_id TEXT PRIMARY KEY,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE CASCADE,
    derivative_kind TEXT NOT NULL,
    storage_file_id TEXT,
    content_sha256 TEXT,
    parameters_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(parameters_json)),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (media_asset_id, derivative_kind, parameters_json)
) STRICT;

CREATE TABLE analysis_jobs (
    analysis_job_id TEXT PRIMARY KEY,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE CASCADE,
    control_job_id TEXT UNIQUE,
    handler_type TEXT NOT NULL,
    handler_version TEXT NOT NULL,
    profile TEXT NOT NULL,
    status TEXT NOT NULL,
    input_digest TEXT NOT NULL,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE analysis_artifacts (
    analysis_artifact_id TEXT PRIMARY KEY,
    analysis_job_id TEXT NOT NULL REFERENCES analysis_jobs(analysis_job_id) ON DELETE CASCADE,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE CASCADE,
    artifact_kind TEXT NOT NULL,
    storage_file_id TEXT,
    artifact_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(artifact_json)),
    content_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (analysis_job_id, artifact_kind, content_digest)
) STRICT;

CREATE TABLE media_segments (
    media_segment_id TEXT PRIMARY KEY,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE CASCADE,
    analysis_artifact_id TEXT REFERENCES analysis_artifacts(analysis_artifact_id) ON DELETE SET NULL,
    segment_kind TEXT NOT NULL,
    start_us INTEGER NOT NULL CHECK (start_us >= 0),
    end_us INTEGER NOT NULL CHECK (end_us > start_us),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    attributes_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(attributes_json))
) STRICT;

CREATE TABLE transcript_segments (
    transcript_segment_id TEXT PRIMARY KEY,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE CASCADE,
    analysis_artifact_id TEXT REFERENCES analysis_artifacts(analysis_artifact_id) ON DELETE SET NULL,
    start_us INTEGER NOT NULL CHECK (start_us >= 0),
    end_us INTEGER NOT NULL CHECK (end_us > start_us),
    text TEXT NOT NULL,
    language TEXT,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
) STRICT;

CREATE TABLE transcript_words (
    transcript_word_id TEXT PRIMARY KEY,
    transcript_segment_id TEXT NOT NULL REFERENCES transcript_segments(transcript_segment_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    start_us INTEGER NOT NULL CHECK (start_us >= 0),
    end_us INTEGER NOT NULL CHECK (end_us > start_us),
    text TEXT NOT NULL,
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    UNIQUE (transcript_segment_id, ordinal)
) STRICT;

CREATE TABLE speaker_turns (
    speaker_turn_id TEXT PRIMARY KEY,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE CASCADE,
    analysis_artifact_id TEXT REFERENCES analysis_artifacts(analysis_artifact_id) ON DELETE SET NULL,
    speaker_label TEXT NOT NULL,
    start_us INTEGER NOT NULL CHECK (start_us >= 0),
    end_us INTEGER NOT NULL CHECK (end_us > start_us),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
) STRICT;

CREATE TABLE ocr_spans (
    ocr_span_id TEXT PRIMARY KEY,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE CASCADE,
    analysis_artifact_id TEXT REFERENCES analysis_artifacts(analysis_artifact_id) ON DELETE SET NULL,
    start_us INTEGER NOT NULL CHECK (start_us >= 0),
    end_us INTEGER NOT NULL CHECK (end_us > start_us),
    text TEXT NOT NULL,
    bounds_json TEXT NOT NULL CHECK (json_valid(bounds_json)),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
) STRICT;

CREATE TABLE semantic_documents (
    semantic_document_id TEXT PRIMARY KEY,
    media_asset_id TEXT NOT NULL REFERENCES media_assets(media_asset_id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    start_us INTEGER CHECK (start_us IS NULL OR start_us >= 0),
    end_us INTEGER CHECK (end_us IS NULL OR (start_us IS NOT NULL AND end_us > start_us)),
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    UNIQUE (source_kind, source_entity_id)
) STRICT;

CREATE TABLE embedding_records (
    embedding_record_id TEXT PRIMARY KEY,
    semantic_document_id TEXT NOT NULL REFERENCES semantic_documents(semantic_document_id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    vector_ref TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (semantic_document_id, model_id, model_version)
) STRICT;

CREATE TABLE edit_sessions (
    edit_session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    base_revision_id TEXT NOT NULL REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    actor_kind TEXT NOT NULL,
    actor_id TEXT,
    request_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE edit_proposals (
    edit_proposal_id TEXT PRIMARY KEY,
    edit_session_id TEXT NOT NULL REFERENCES edit_sessions(edit_session_id) ON DELETE CASCADE,
    base_revision_id TEXT NOT NULL REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    assumptions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(assumptions_json)),
    evidence_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_json)),
    estimated_cost_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(estimated_cost_json)),
    applied_revision_id TEXT REFERENCES project_revisions(revision_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE edit_operations (
    edit_operation_id TEXT PRIMARY KEY,
    edit_proposal_id TEXT NOT NULL REFERENCES edit_proposals(edit_proposal_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    operation_type TEXT NOT NULL,
    operation_json TEXT NOT NULL CHECK (json_valid(operation_json)),
    preconditions_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(preconditions_json)),
    created_at TEXT NOT NULL,
    UNIQUE (edit_proposal_id, ordinal)
) STRICT;

CREATE TABLE render_jobs (
    render_job_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES project_revisions(revision_id) ON DELETE RESTRICT,
    control_job_id TEXT UNIQUE,
    preset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    output_name TEXT NOT NULL,
    settings_json TEXT NOT NULL CHECK (json_valid(settings_json)),
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE render_artifacts (
    render_artifact_id TEXT PRIMARY KEY,
    render_job_id TEXT NOT NULL REFERENCES render_jobs(render_job_id) ON DELETE CASCADE,
    artifact_kind TEXT NOT NULL,
    storage_file_id TEXT,
    content_sha256 TEXT,
    technical_report_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(technical_report_json)),
    validated_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (render_job_id, artifact_kind)
) STRICT;

CREATE TABLE templates (
    template_version_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    registry_owner TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    content_digest TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (template_id, version)
) STRICT;

CREATE TABLE style_recipes (
    style_recipe_version_id TEXT PRIMARY KEY,
    style_recipe_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    recipe_json TEXT NOT NULL CHECK (json_valid(recipe_json)),
    content_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (style_recipe_id, version)
) STRICT;

CREATE TABLE audit_events (
    audit_event_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
    actor_kind TEXT NOT NULL,
    actor_id TEXT,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    correlation_id TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json)),
    created_at TEXT NOT NULL
) STRICT;

CREATE INDEX idx_project_revisions_project_created
    ON project_revisions(project_id, created_at DESC);
CREATE INDEX idx_project_revisions_parent ON project_revisions(parent_revision_id);
CREATE INDEX idx_project_revisions_edit_session ON project_revisions(edit_session_id);
CREATE INDEX idx_project_branches_project ON project_branches(project_id);
CREATE INDEX idx_project_branches_head ON project_branches(head_revision_id);
CREATE INDEX idx_project_assets_project ON project_assets(project_id);
CREATE INDEX idx_project_assets_media ON project_assets(media_asset_id);
CREATE INDEX idx_project_assets_added_revision ON project_assets(added_revision_id);
CREATE INDEX idx_media_assets_status ON media_assets(status, created_at);
CREATE INDEX idx_media_derivatives_asset ON media_derivatives(media_asset_id, derivative_kind);
CREATE INDEX idx_analysis_jobs_asset_status ON analysis_jobs(media_asset_id, status);
CREATE INDEX idx_analysis_artifacts_asset_kind ON analysis_artifacts(media_asset_id, artifact_kind);
CREATE INDEX idx_media_segments_asset_time ON media_segments(media_asset_id, start_us, end_us);
CREATE INDEX idx_media_segments_artifact ON media_segments(analysis_artifact_id);
CREATE INDEX idx_transcript_segments_asset_time ON transcript_segments(media_asset_id, start_us, end_us);
CREATE INDEX idx_transcript_segments_artifact ON transcript_segments(analysis_artifact_id);
CREATE INDEX idx_speaker_turns_asset_time ON speaker_turns(media_asset_id, start_us, end_us);
CREATE INDEX idx_speaker_turns_artifact ON speaker_turns(analysis_artifact_id);
CREATE INDEX idx_ocr_spans_asset_time ON ocr_spans(media_asset_id, start_us, end_us);
CREATE INDEX idx_ocr_spans_artifact ON ocr_spans(analysis_artifact_id);
CREATE INDEX idx_semantic_documents_asset_time ON semantic_documents(media_asset_id, start_us, end_us);
CREATE INDEX idx_edit_sessions_project_status ON edit_sessions(project_id, status, updated_at);
CREATE INDEX idx_edit_sessions_base_revision ON edit_sessions(base_revision_id);
CREATE INDEX idx_edit_proposals_session_status ON edit_proposals(edit_session_id, status);
CREATE INDEX idx_edit_proposals_base_revision ON edit_proposals(base_revision_id);
CREATE INDEX idx_edit_proposals_applied_revision ON edit_proposals(applied_revision_id);
CREATE INDEX idx_render_jobs_project_status ON render_jobs(project_id, status, updated_at);
CREATE INDEX idx_render_jobs_revision ON render_jobs(revision_id);
CREATE INDEX idx_audit_events_project_created ON audit_events(project_id, created_at DESC);
