"""FTS5 over visible text, address values and attachment names."""

import re


def _addresses(column):
    return f"COALESCE((SELECT group_concat(CAST(value AS TEXT), ' ') FROM json_tree({column}) WHERE type = 'text'), '')"


def install_search_index(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS mail_search (
          id TEXT PRIMARY KEY, thread_id TEXT NOT NULL DEFAULT '',
          message_id TEXT NOT NULL DEFAULT '', draft_id TEXT NOT NULL DEFAULT '', text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mail_search_thread ON mail_search(thread_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts USING fts5(text, content='mail_search', content_rowid='rowid', prefix='2 3 4');
        CREATE TRIGGER IF NOT EXISTS mail_search_ai AFTER INSERT ON mail_search BEGIN
          INSERT INTO mail_fts(rowid, text) VALUES (NEW.rowid, NEW.text);
        END;
        CREATE TRIGGER IF NOT EXISTS mail_search_ad AFTER DELETE ON mail_search BEGIN
          INSERT INTO mail_fts(mail_fts, rowid, text) VALUES ('delete', OLD.rowid, OLD.text);
        END;
        CREATE TRIGGER IF NOT EXISTS mail_search_au AFTER UPDATE ON mail_search BEGIN
          INSERT INTO mail_fts(mail_fts, rowid, text) VALUES ('delete', OLD.rowid, OLD.text);
          INSERT INTO mail_fts(rowid, text) VALUES (NEW.rowid, NEW.text);
        END;
        CREATE TABLE IF NOT EXISTS thread_labels (
          thread_id TEXT NOT NULL, label TEXT NOT NULL, PRIMARY KEY(thread_id, label)
        );
        CREATE INDEX IF NOT EXISTS idx_thread_labels_label ON thread_labels(label, thread_id);
        CREATE TRIGGER IF NOT EXISTS thread_labels_ai AFTER INSERT ON threads BEGIN
          INSERT OR IGNORE INTO thread_labels SELECT NEW.id, value FROM json_each(NEW.labels_json);
        END;
        CREATE TRIGGER IF NOT EXISTS thread_labels_au AFTER UPDATE OF labels_json ON threads BEGIN
          DELETE FROM thread_labels WHERE thread_id = OLD.id;
          INSERT OR IGNORE INTO thread_labels SELECT NEW.id, value FROM json_each(NEW.labels_json);
        END;
        CREATE TRIGGER IF NOT EXISTS thread_labels_ad AFTER DELETE ON threads BEGIN
          DELETE FROM thread_labels WHERE thread_id = OLD.id;
        END;
    """)
    builders = {
        "threads": lambda alias: f"SELECT 'thread:' || id, id, '', '', subject || ' ' || snippet || ' ' || {_addresses('participants_json')} FROM threads WHERE id = {alias}.id",
        "messages": lambda alias: f"SELECT 'message:' || id, thread_id, id, '', body_text || ' ' || {_addresses('sender_json')} || ' ' || {_addresses('recipients_json')} || ' ' || {_addresses('cc_json')} || ' ' || {_addresses('bcc_json')} || ' ' || COALESCE((SELECT group_concat(filename, ' ') FROM attachments WHERE message_id = messages.id), '') FROM messages WHERE id = {alias}.id",
        "drafts": lambda alias: f"SELECT 'draft:' || id, '', '', id, subject || ' ' || body_text || ' ' || {_addresses('to_json')} || ' ' || {_addresses('cc_json')} || ' ' || {_addresses('bcc_json')} FROM drafts WHERE id = {alias}.id",
    }
    db.execute("DELETE FROM mail_search")
    for table, builder in builders.items():
        prefix = {"threads": "thread", "messages": "message", "drafts": "draft"}[table]
        for event, alias in [("INSERT", "NEW"), ("UPDATE", "NEW")]:
            old_delete = f"DELETE FROM mail_search WHERE id = '{prefix}:' || OLD.id;" if event == "UPDATE" else ""
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS search_{table}_{event.lower()} AFTER {event} ON {table} BEGIN
                {old_delete}
                DELETE FROM mail_search WHERE id = '{prefix}:' || {alias}.id;
                INSERT INTO mail_search(id, thread_id, message_id, draft_id, text) {builder(alias)};
            END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS search_{table}_delete AFTER DELETE ON {table} BEGIN
            DELETE FROM mail_search WHERE id = '{prefix}:' || OLD.id;
        END""")
        # Initial backfill is performed only by the versioned migration.
        db.execute(f"INSERT INTO mail_search(id, thread_id, message_id, draft_id, text) {builder(table).replace(f' WHERE id = {table}.id', '')}")
    for event, alias in [("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")]:
        # UPDATE may reassign the attachment: rebuild both old and new messages.
        ids = "OLD.message_id, NEW.message_id" if event == "UPDATE" else f"{alias}.message_id"
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS search_attachments_{event.lower()} AFTER {event} ON attachments BEGIN
            UPDATE messages SET body_text = body_text WHERE id IN ({ids});
        END""")
    db.execute("INSERT OR IGNORE INTO thread_labels SELECT threads.id, value FROM threads, json_each(threads.labels_json)")


def search_predicate(query, column, *, search_field, thread_documents_only=False):
    """Words are literal prefixes joined with AND; punctuation-only is literal."""
    if search_field not in {"thread_id", "message_id", "draft_id"}:
        raise ValueError("Invalid mail search field")
    document_filter = "message_id = '' AND " if thread_documents_only else ""
    words = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    if words:
        match = " AND ".join('"' + word.replace('"', '""') + '"*' for word in words)
        condition = "rowid IN (SELECT rowid FROM mail_fts WHERE mail_fts MATCH ?)"
        parameters = [match]
    else:
        condition = "instr(text, ?) > 0"
        parameters = [query]
    return f"{column} IN (SELECT {search_field} FROM mail_search WHERE {document_filter}{condition})", parameters
