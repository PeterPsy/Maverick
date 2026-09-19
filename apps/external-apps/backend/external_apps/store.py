"""SQLite adapter for private catalog/plans/audit; no active binding pointer."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from .errors import AppError
from .files import encoded

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS apps(id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY, app_id TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS releases_app ON releases(app_id,created);
CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, app_id TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS plans_app ON plans(app_id,created);
CREATE INDEX IF NOT EXISTS plans_expired ON plans(expires) WHERE status!='applied';
CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, app_id TEXT NOT NULL, created REAL NOT NULL, done INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS operations_app ON operations(app_id,created);
CREATE INDEX IF NOT EXISTS operations_pending ON operations(done,created);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, app_id TEXT NOT NULL, created REAL NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_app ON audit(app_id,id);
PRAGMA user_version=1;
"""


class Store:
    def __init__(self, root: Path, workspace_id: str):
        self.root = root
        self.workspace_id = workspace_id
        self.path = root / "app.sqlite"

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise AppError("schema_version_unsupported", 503)
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO settings VALUES('workspace_id',?)", (self.workspace_id,))
        self.assert_workspace()

    @contextmanager
    def connection(self, *, readonly=False):
        if readonly:
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
        else:
            db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            if not readonly:
                db.execute("PRAGMA synchronous=FULL")
            yield db
            if not readonly:
                db.commit()
        except BaseException:
            if not readonly:
                db.rollback()
            raise
        finally:
            db.close()

    def assert_workspace(self):
        if not self.path.exists():
            return
        with self.connection(readonly=True) as db:
            row = db.execute("SELECT value FROM settings WHERE key='workspace_id'").fetchone()
            if not row or row[0] != self.workspace_id:
                raise AppError("workspace_mismatch", 403)

    def get(self, table, key):
        self._table(table)
        self.assert_workspace()
        if not self.path.exists():
            raise AppError("not_found", 404)
        with self.connection(readonly=True) as db:
            row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (key,)).fetchone()
        if row is None:
            raise AppError("not_found", 404)
        return json.loads(row[0])

    def list(self, table, *, app_id=None, limit=100, offset=0):
        self._table(table)
        self.assert_workspace()
        if not self.path.exists():
            return []
        if not 1 <= limit <= 1000 or not 0 <= offset <= 100000:
            raise AppError("invalid_pagination")
        clause = " WHERE app_id=?" if app_id is not None else ""
        params = [app_id] if app_id is not None else []
        with self.connection(readonly=True) as db:
            rows = db.execute(f"SELECT payload FROM {table}{clause} ORDER BY created DESC,id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, table, payload, *, insert=False):
        self._table(table)
        self.assert_workspace()
        columns = ["id", "created", "payload"]
        values = [payload["id"], payload["created"], encoded(payload).decode()]
        if table != "apps":
            columns += ["app_id"]
            values += [payload["app_id"]]
        if table == "plans":
            columns += ["expires", "status"]
            values += [payload["expires"], payload["status"]]
        if table == "operations":
            columns += ["idem", "done"]
            values += [payload["idem"], int(payload.get("result") is not None)]
        command = "INSERT" if insert else "INSERT OR REPLACE"
        if table == "releases" and not insert:
            raise AppError("release_is_immutable")
        with self.connection() as db:
            db.execute(f"{command} INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)

    def operation(self, idem):
        self.assert_workspace()
        if not self.path.exists():
            return None
        with self.connection(readonly=True) as db:
            row = db.execute("SELECT payload FROM operations WHERE idem=?", (idem,)).fetchone()
        return json.loads(row[0]) if row else None

    def unfinished(self):
        if not self.path.exists():
            return []
        with self.connection(readonly=True) as db:
            rows = db.execute("SELECT payload FROM operations WHERE done=0 ORDER BY created LIMIT 100").fetchall()
        return [json.loads(row[0]) for row in rows]

    def audit(self, app_id, action, actor, detail=""):
        with self.connection() as db:
            db.execute("INSERT INTO audit(app_id,created,action,actor,detail) VALUES(?,?,?,?,?)",
                       (app_id, time.time(), action, actor, detail[:240]))

    def history(self, app_id):
        if not self.path.exists():
            return []
        with self.connection(readonly=True) as db:
            return [dict(row) for row in db.execute("SELECT created,action,actor,detail FROM audit WHERE app_id=? ORDER BY id DESC LIMIT 30", (app_id,))]

    @staticmethod
    def _table(table):
        if table not in {"apps", "releases", "plans", "operations"}:
            raise AppError("invalid_table")
