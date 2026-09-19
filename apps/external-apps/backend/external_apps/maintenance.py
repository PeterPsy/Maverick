"""Small bounded housekeeping, not a retention framework; caller holds writer lock."""
import json
import shutil
import time

from .errors import AppError
from .bindings import read_binding


def cleanup(store):
    now = time.time()
    # The public pointer, not SQLite, is authoritative, including after a crash.
    pinned_ids, pinned_digests = set(), set()
    bindings = store.root / "public/bindings"
    if bindings.is_dir():
        for path in bindings.iterdir():
            if path.suffix != ".json":
                continue
            binding = read_binding(store.root / "public", path.stem)
            for release in (binding.get("current"), binding.get("previous")):
                if release:
                    pinned_ids.add(release["release_id"])
                    pinned_digests.add(release["digest"])
    with store.connection() as db:
        expired = db.execute("SELECT id,payload FROM plans WHERE expires<? AND status!='applied' ORDER BY expires LIMIT 100", (now,)).fetchall()
        for row in expired:
            plan = json.loads(row["payload"])
            release_id = plan.get("release", {}).get("release_id") or plan.get("release_id")
            # Expiring a rollback plan must never delete a previously used release.
            if release_id and plan["kind"] == "publish" and release_id not in pinned_ids:
                db.execute("DELETE FROM releases WHERE id=?", (release_id,))
            db.execute("DELETE FROM plans WHERE id=?", (row["id"],))
        retained = pinned_digests | {json.loads(row[0])["digest"] for row in db.execute("SELECT payload FROM releases")}
    artifacts = store.root / "public/artifacts"
    if artifacts.is_dir():
        for directory in list(artifacts.iterdir())[:1000]:
            if directory.name not in retained and directory.is_dir() and not directory.is_symlink() and directory.stat().st_mtime < now - 3600:
                shutil.rmtree(directory)
    tmp = store.root / "tmp"
    if tmp.is_dir():
        for directory in list(tmp.iterdir())[:100]:
            if directory.name.startswith("bundle-") and directory.is_dir() and not directory.is_symlink() and directory.stat().st_mtime < now - 3600:
                shutil.rmtree(directory)


def capacity(store):
    with store.connection(readonly=True) as db:
        if db.execute("SELECT count(*) FROM plans").fetchone()[0] >= 2000:
            raise AppError("plan_capacity_reached", 409)
        if db.execute("SELECT count(*) FROM operations").fetchone()[0] >= 10000:
            raise AppError("operation_capacity_reached", 409)
