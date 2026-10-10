"""Remove provider-deleted cache rows and their dependent metadata."""


def remove_messages(db, message_ids):
    for message_id in message_ids:
        db.execute("""DELETE FROM entity_links WHERE
        (source_entity_type='mail_attachment' AND source_entity_id IN (SELECT id FROM attachments WHERE message_id=?)) OR
        (target_app_id='mail' AND target_entity_type='mail_attachment' AND target_entity_id IN (SELECT id FROM attachments WHERE message_id=?))""", (message_id, message_id))
        db.execute("DELETE FROM attachments WHERE message_id=?", (message_id,))
        db.execute("DELETE FROM messages WHERE id=?", (message_id,))
        db.execute("DELETE FROM entity_links WHERE (source_entity_type='email_message' AND source_entity_id=?) OR (target_app_id='mail' AND target_entity_type='email_message' AND target_entity_id=?)", (message_id, message_id))


def remove_thread(db, thread_id):
    remove_messages(db, [row[0] for row in db.execute("SELECT id FROM messages WHERE thread_id=?", (thread_id,))])
    db.execute("DELETE FROM threads WHERE id=?", (thread_id,))
    db.execute("DELETE FROM entity_links WHERE (source_entity_type='email_thread' AND source_entity_id=?) OR (target_app_id='mail' AND target_entity_type='email_thread' AND target_entity_id=?)", (thread_id, thread_id))
