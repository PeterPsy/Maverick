"""Actor-scoped collections and durable operation/request records."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO meta VALUES('schema_version','1');
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,source TEXT NOT NULL,operation TEXT NOT NULL,
 parameters TEXT NOT NULL,status TEXT NOT NULL,phase TEXT NOT NULL DEFAULT '',browser_id TEXT,result TEXT NOT NULL DEFAULT '{}',
 error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS runs_owner ON runs(owner,created_at);
CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,alias TEXT NOT NULL,body TEXT NOT NULL,
 phase TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS connections(owner TEXT PRIMARY KEY,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS collections(id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL,source TEXT NOT NULL,
 parameters TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,collection_id TEXT NOT NULL,url TEXT NOT NULL,payload TEXT NOT NULL,
 first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,UNIQUE(collection_id,url));
CREATE INDEX IF NOT EXISTS items_collection ON items(collection_id,last_seen);
CREATE TABLE IF NOT EXISTS views(owner TEXT PRIMARY KEY,payload TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


def encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",",":"))


@contextmanager
def database(root: Path):
    root = Path(root)
    if root.is_symlink():
        raise ValueError("The app data directory cannot be a symbolic link.")
    root.mkdir(parents=True, exist_ok=True)
    path = root / "connectors.sqlite3"
    if path.is_symlink():
        raise ValueError("The database cannot be a symbolic link.")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os,"O_NOFOLLOW",0), 0o600)
    os.close(descriptor)
    os.chmod(path,0o600)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.executescript(SCHEMA)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE runs SET status='failed',phase='expired',error='The operation expired before it completed.' WHERE status IN ('pending','waiting','running') AND julianday(updated_at) < julianday('now','-30 minutes')")
        owners = db.execute("SELECT DISTINCT owner FROM runs").fetchall()
        for owner in owners:
            retained = db.execute("SELECT id,length(result) AS size FROM runs WHERE owner=? AND status IN ('completed','failed','cancelled') ORDER BY created_at DESC",(owner[0],)).fetchall()
            total = 0
            for index,row in enumerate(retained):
                total += row["size"]
                if index>=200 or total>32*1024*1024:
                    db.execute("DELETE FROM requests WHERE run_id=?",(row["id"],))
                    db.execute("DELETE FROM runs WHERE id=?",(row["id"],))
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def public_run(row) -> dict:
    return {key:row[key] for key in ("id","source","operation","status","phase","error","created_at","updated_at")} | {
        "parameters":json.loads(row["parameters"]),"result":json.loads(row["result"]),
        "deep_link":f"/app/platform-connectors?run_id={row['id']}"}


def owned_run(db, run_id: str, owner: str):
    row = db.execute("SELECT * FROM runs WHERE id=? AND owner=?",(run_id,owner)).fetchone()
    if row is None:
        raise LookupError("This operation is unavailable for this user.")
    return row


def create_run(db, owner: str, source: str, operation: str, parameters: dict) -> dict:
    session = parameters.get("session_id")
    if session:
        active = db.execute("SELECT parameters FROM runs WHERE owner=? AND status IN ('pending','waiting','running')",(owner,)).fetchall()
        if any(json.loads(row["parameters"]).get("session_id") == session for row in active):
            raise ValueError("This shared tab is already observing a source. Wait or cancel that operation before starting another.")
    count = db.execute("SELECT count(*) FROM runs WHERE owner=? AND status IN ('pending','waiting','running')",(owner,)).fetchone()[0]
    if count >= 12:
        raise ValueError("There are already 12 active operations. Wait or cancel one.")
    identifier,stamp = str(uuid4()),now()
    db.execute("INSERT INTO runs(id,owner,source,operation,parameters,status,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)",
               (identifier,owner,source,operation,encoded(parameters),stamp,stamp))
    return public_run(owned_run(db,identifier,owner))


def update_run(db, run_id: str, **fields):
    if set(fields) - {"status","phase","browser_id","result","parameters","error"}:
        raise ValueError("Invalid operation field.")
    values = {key:encoded(value) if key in {"result","parameters"} else value for key,value in fields.items()}
    if "result" in values and len(values["result"].encode())>8*1024*1024:
        raise ValueError("The observation reached its 8 MiB result limit. Earlier observations are retained.")
    values["updated_at"] = now()
    db.execute("UPDATE runs SET " + ",".join(key+"=?" for key in values) + " WHERE id=?",(*values.values(),run_id))


def save_collection(db, owner: str, title: str, run: dict) -> dict:
    identifier,stamp = str(uuid4()),now()
    saved_parameters = run["parameters"] | {"_operation":run["operation"]}
    db.execute("INSERT INTO collections VALUES(?,?,?,?,?,?,?)",(identifier,owner,title,run["source"],encoded(saved_parameters),stamp,stamp))
    saved_result = run.get("result",{})
    add_items(db,identifier,saved_result.get("context_items",[]) + saved_result.get("items",[]))
    return collection(db,owner,identifier)


def add_items(db, collection_id: str, items: list[dict]):
    stamp = now()
    for item in items[:500]:
        url = str(item.get("url") or "")[:2048]
        if not url:
            continue
        identifier = hashlib.sha256((collection_id+"\0"+url).encode()).hexdigest()[:32]
        db.execute("INSERT INTO items VALUES(?,?,?,?,?,?) ON CONFLICT(collection_id,url) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen",
                   (identifier,collection_id,url,encoded(item),stamp,stamp))
    db.execute("UPDATE collections SET updated_at=? WHERE id=?",(stamp,collection_id))


def collection(db, owner: str, identifier: str, *, offset: int = 0, limit: int = 100) -> dict:
    row = db.execute("SELECT * FROM collections WHERE id=? AND owner=?",(identifier,owner)).fetchone()
    if row is None:
        raise LookupError("Collection unavailable.")
    total = db.execute("SELECT count(*) FROM items WHERE collection_id=?",(identifier,)).fetchone()[0]
    items = db.execute("SELECT payload FROM items WHERE collection_id=? ORDER BY last_seen DESC LIMIT ? OFFSET ?",(identifier,limit,offset)).fetchall()
    return dict(row) | {"parameters":json.loads(row["parameters"]),"items":[json.loads(item["payload"]) for item in items],
                       "total":total,"offset":offset,"has_more":offset+len(items)<total,"next_offset":offset+len(items),
                       "deep_link":f"/app/platform-connectors?collection_id={identifier}"}
