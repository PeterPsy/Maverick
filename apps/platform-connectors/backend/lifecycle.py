"""Idempotent private schema and pinned, app-owned media reader lifecycle."""

import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from media_source import YT_DLP_VERSION
from store import database


def installed_version(root):
    try:
        return next(d.version for d in importlib.metadata.distributions(path=[str(root/"vendor")]) if d.metadata["Name"] == "yt-dlp")
    except StopIteration:
        return None


def lifecycle(root: Path, action: str):
    with database(root) as db:
        integrity = db.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            return {"ok":False,"error":"database_integrity_failed"}
    if action != "health_check" and installed_version(root) != YT_DLP_VERSION:
        with TemporaryDirectory(prefix="media-install-",dir=root) as staging:
            process = subprocess.run([sys.executable,"-m","pip","install","--disable-pip-version-check","--no-input",
                                      "--target",staging,"yt-dlp[default]=="+YT_DLP_VERSION],capture_output=True,timeout=90,check=False)
            if process.returncode:
                return {"ok":False,"error":"media_runtime_install_failed","detail":"The pinned YouTube reader could not be installed from PyPI."}
            vendor = root/"vendor"
            if vendor.is_symlink():
                raise ValueError("The media runtime directory cannot be a symbolic link.")
            if vendor.exists():
                shutil.rmtree(vendor)
            Path(staging).rename(vendor)
    return {"ok":installed_version(root) == YT_DLP_VERSION,"schema_version":"1","media_reader_version":installed_version(root)}
