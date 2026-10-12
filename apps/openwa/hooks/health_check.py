"""App database and configured OpenWA provider readiness."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from gateway import GatewayError, check_readiness
from state import configuration


def health(data_root):
    if not (Path(data_root) / "app.sqlite").is_file():
        return {"ok": False, "detail": "The app database does not exist."}
    try:
        check_readiness(configuration(data_root)["url"])
    except GatewayError as error:
        return {"ok": False, "detail": str(error), "error": error.code}
    return {"ok": True}


if __name__ == "__main__":
    emit_json(health(read_entrypoint_payload().data_root))
