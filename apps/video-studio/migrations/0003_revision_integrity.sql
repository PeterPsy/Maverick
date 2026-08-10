CREATE TRIGGER project_revisions_immutable_update
BEFORE UPDATE ON project_revisions
BEGIN
    SELECT RAISE(ABORT, 'project revisions are immutable');
END;

CREATE TRIGGER project_revisions_immutable_delete
BEFORE DELETE ON project_revisions
BEGIN
    SELECT RAISE(ABORT, 'project revisions are immutable');
END;

CREATE TRIGGER project_revisions_parent_project_insert
BEFORE INSERT ON project_revisions
WHEN NEW.parent_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM project_revisions parent
    WHERE parent.revision_id = NEW.parent_revision_id
      AND parent.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'revision parent belongs to another project');
END;

CREATE TRIGGER project_branches_revision_project_insert
BEFORE INSERT ON project_branches
WHEN NEW.head_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.head_revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'branch revision belongs to another project');
END;

CREATE TRIGGER project_branches_revision_project_update
BEFORE UPDATE OF project_id, head_revision_id ON project_branches
WHEN NEW.head_revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.head_revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'branch revision belongs to another project');
END;

CREATE TRIGGER project_projections_revision_project_insert
BEFORE INSERT ON project_projections
WHEN NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'projection revision belongs to another project');
END;

CREATE TRIGGER project_projections_revision_project_update
BEFORE UPDATE OF project_id, revision_id ON project_projections
WHEN NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'projection revision belongs to another project');
END;

CREATE TRIGGER project_batches_revision_project_insert
BEFORE INSERT ON project_operation_batches
WHEN NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.base_revision_id
      AND revision.project_id = NEW.project_id
 )
 OR NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.result_revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'operation batch revision belongs to another project');
END;

CREATE TRIGGER project_batches_revision_project_update
BEFORE UPDATE OF project_id, base_revision_id, result_revision_id ON project_operation_batches
WHEN NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.base_revision_id
      AND revision.project_id = NEW.project_id
 )
 OR NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.result_revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'operation batch revision belongs to another project');
END;

CREATE TRIGGER project_autosaves_revision_project_insert
BEFORE INSERT ON project_autosaves
WHEN NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'autosave revision belongs to another project');
END;

CREATE TRIGGER project_autosaves_revision_project_update
BEFORE UPDATE OF project_id, revision_id ON project_autosaves
WHEN NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'autosave revision belongs to another project');
END;

CREATE TRIGGER project_outbox_revision_project_insert
BEFORE INSERT ON project_outbox
WHEN NEW.revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'outbox revision belongs to another project');
END;

CREATE TRIGGER project_outbox_revision_project_update
BEFORE UPDATE OF project_id, revision_id ON project_outbox
WHEN NEW.revision_id IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM project_revisions revision
    WHERE revision.revision_id = NEW.revision_id
      AND revision.project_id = NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'outbox revision belongs to another project');
END;

CREATE TRIGGER project_navigation_revision_project_insert
BEFORE INSERT ON project_revision_navigation
WHEN EXISTS (
    SELECT 1
    FROM json_each(NEW.undo_stack_json || '') stack
    LEFT JOIN project_revisions revision ON revision.revision_id = stack.value
    WHERE revision.revision_id IS NULL OR revision.project_id != NEW.project_id
 )
 OR EXISTS (
    SELECT 1
    FROM json_each(NEW.redo_stack_json || '') stack
    LEFT JOIN project_revisions revision ON revision.revision_id = stack.value
    WHERE revision.revision_id IS NULL OR revision.project_id != NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'navigation revision belongs to another project');
END;

CREATE TRIGGER project_navigation_revision_project_update
BEFORE UPDATE OF project_id, undo_stack_json, redo_stack_json ON project_revision_navigation
WHEN EXISTS (
    SELECT 1
    FROM json_each(NEW.undo_stack_json || '') stack
    LEFT JOIN project_revisions revision ON revision.revision_id = stack.value
    WHERE revision.revision_id IS NULL OR revision.project_id != NEW.project_id
 )
 OR EXISTS (
    SELECT 1
    FROM json_each(NEW.redo_stack_json || '') stack
    LEFT JOIN project_revisions revision ON revision.revision_id = stack.value
    WHERE revision.revision_id IS NULL OR revision.project_id != NEW.project_id
 )
BEGIN
    SELECT RAISE(ABORT, 'navigation revision belongs to another project');
END;

UPDATE app_metadata
SET value = '3', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE key = 'schema_version';
