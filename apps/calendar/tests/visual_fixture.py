"""Foreground-only authenticated visual fixture; never uses workspace data.

Run from the Maverick root with .venv/bin/python -m apps.calendar.tests.visual_fixture.
The isolated account is calendar-visual-test / calendar-visual-fixture.
Ctrl-C shuts down the backend scheduler and removes all temporary state.
"""

from datetime import UTC, datetime, timedelta
from dataclasses import replace
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo


def main():
    import uvicorn
    from core.api.asgi_application import PlatformAsgiHost
    from core.api.background_hooks import start_background_hook_scheduler
    from core.api.platform_state import bootstrap_platform_state
    from core.shared.entrypoints import (
        EntrypointShutdownController,
        run_json_entrypoint,
    )

    source = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="calendar-visual-") as directory:
        root = Path(directory)
        for name in ("core", "apps", "workspaces", "scripts"):
            (root / name).mkdir()
        (root / "AGENTS.md").write_text("Calendar visual fixture only.\n")
        key_file = root / "fixture-secret.key"
        key_file.write_text(os.urandom(32).hex())
        key_file.chmod(0o600)
        for app_id in ("base-shell", "calendar", "app-store", "checklist"):
            (root / "apps" / app_id).symlink_to(
                source / "apps" / app_id, target_is_directory=True
            )
        os.environ.update(
            {
                "MAVERICK_CONTROL_STORE": "json",
                "MAVERICK_JSON_CONTROL_STORE_ROOT": str(root / "control"),
                "MAVERICK_ADMIN_USERNAME": "calendar-visual-test",
                "MAVERICK_ADMIN_PASSWORD": "calendar-visual-fixture",
                "MAVERICK_SECRET_KEY_FILE": str(key_file),
                "MAVERICK_ADMIN_PASSWORD_REF": "",
                "MAVERICK_SIDECAR_ORIGIN_MODE": "local",
            }
        )
        state = bootstrap_platform_state(
            start_path=root, register_builtin_provider_definitions=False
        )
        user = state.identity_store.get_user_by_username("calendar-visual-test")
        state.identity_store.save_user(replace(user, platform_role="user"))
        pins = state.app_store.get_workspace_app_binding(
            workspace_id="default", app_id="app-store"
        )
        pinned = run_json_entrypoint(
            source / "apps/app-store/backend/app_backend.py",
            cwd=source / "apps/app-store",
            payload={
                "app_id": "app-store",
                "workspace_id": "default",
                "data_root": pins.data_root,
                "workspace_apps": {
                    "items": [
                        {"app_id": app_id, "frontend_launchable": True}
                        for app_id in ("calendar", "checklist", "app-store")
                    ]
                },
                "body": {
                    "action": "pinned_apps.set",
                    "app_ids": ["calendar", "checklist"],
                },
            },
        )
        if pinned["status_code"] != 200:
            raise RuntimeError(pinned["json"])
        binding = state.app_store.get_workspace_app_binding(
            workspace_id="default", app_id="calendar"
        )
        now = datetime.now(UTC)
        today = now.astimezone(ZoneInfo("Europe/Rome"))
        morning = today.replace(hour=9, minute=30, second=0, microsecond=0)
        events = [
            {
                "title": "Evento 09:30–11:00",
                "startTime": morning.isoformat(),
                "endTime": (morning + timedelta(minutes=90)).isoformat(),
            },
            {
                "title": "Sovrapposizione 10:15",
                "startTime": (morning + timedelta(minutes=45)).isoformat(),
                "endTime": (morning + timedelta(minutes=105)).isoformat(),
            },
            {
                "title": "Giornata intera",
                "startTime": today.date().isoformat(),
                "endTime": (today + timedelta(days=1)).date().isoformat(),
                "all_day": True,
            },
            {
                "title": "Serie settimanale",
                "startTime": (morning + timedelta(hours=4)).isoformat(),
                "endTime": (morning + timedelta(hours=5)).isoformat(),
                "recurrence": {"frequency": "weekly", "count": 3},
            },
            {
                "title": "Promemoria con Calendar chiuso",
                "startTime": (now + timedelta(minutes=15)).isoformat(),
                "endTime": (now + timedelta(minutes=45)).isoformat(),
                "reminders": [{"method": "popup", "minutes_before": 15}],
            },
        ]
        for event in events:
            result = run_json_entrypoint(
                source / "apps/calendar/backend/app_backend.py",
                cwd=source / "apps/calendar",
                payload={
                    "app_id": "calendar",
                    "workspace_id": "default",
                    "data_root": binding.data_root,
                    "body": {
                        "action": "create",
                        "event": {"timezone": "Europe/Rome", **event},
                    },
                },
            )
            if result["status_code"] != 201:
                raise RuntimeError(result["json"])
        shutdown = EntrypointShutdownController()
        app = PlatformAsgiHost(state, shutdown_controller=shutdown)
        start_background_hook_scheduler(
            state, interval_seconds=5, shutdown_controller=shutdown
        )
        try:
            uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
        finally:
            shutdown.begin_shutdown()


if __name__ == "__main__":
    main()
