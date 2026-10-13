"""Scheduled-chat notifications in the central Shell inbox."""

from scheduled_store import iso


def notifications(db, body, actor):
    action = body["action"]
    if action == "notifications.list":
        offset, limit = body.get("offset", 0), body.get("limit", 50)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("Use a nonnegative offset and a limit from 1 to 100")
        query = """FROM scheduled_notifications n JOIN scheduled_chats c ON c.id=n.chat_id
            LEFT JOIN scheduled_receipts r ON r.notification_id=n.id AND r.user_id=?
            WHERE n.owner=? AND c.deleted=0 AND COALESCE(r.dismissed,0)=0"""
        rows = db.execute("SELECT n.*,COALESCE(r.read,0) AS is_read " + query + " ORDER BY n.created_at DESC,n.id LIMIT ? OFFSET ?", (actor, actor, limit, offset)).fetchall()
        total, unread = db.execute("SELECT COUNT(*),COALESCE(SUM(CASE WHEN COALESCE(r.read,0)=0 THEN 1 ELSE 0 END),0) " + query, (actor, actor)).fetchone()
        return {"notifications": [{"id": row["id"], "title": row["title"], "body": row["body"],
                    "created_at": iso(row["created_at"]), "read": bool(row["is_read"]),
                    "open_params": {"app_page": "scheduled/" + row["chat_id"]}} for row in rows],
                "total": total, "unread_total": unread, "has_more": offset + len(rows) < total,
                "capabilities": {"read": True, "actions": False}}
    if action not in {"notifications.read", "notifications.dismiss"}:
        raise ValueError("Unknown notification operation")
    if body.get("all") is True and action == "notifications.read" and not body.get("id"):
        ids = [row[0] for row in db.execute("SELECT id FROM scheduled_notifications WHERE owner=?", (actor,))]
    else:
        if body.get("all") or not isinstance(body.get("id"), str):
            raise ValueError("Choose a notification id or read all")
        ids = [row[0] for row in db.execute("SELECT id FROM scheduled_notifications WHERE owner=? AND id=?", (actor, body["id"]))]
        if not ids:
            raise ValueError("Notification not found")
    column = "read" if action == "notifications.read" else "dismissed"
    for notification_id in ids:
        db.execute(f"INSERT INTO scheduled_receipts(notification_id,user_id,{column}) VALUES(?,?,1) "
                   f"ON CONFLICT(notification_id,user_id) DO UPDATE SET {column}=1", (notification_id, actor))
    return {"_notifications_changed": True}
