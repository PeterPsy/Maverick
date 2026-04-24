from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

from core.api.asgi_application import PlatformAsgiHost
from core.shared.entrypoints import EntrypointShutdownController


REPO_ROOT = Path(__file__).resolve().parents[1]


class AsgiApplicationTests(unittest.TestCase):
    def test_http_host_runs_outside_event_loop(self) -> None:
        source = (REPO_ROOT / "core/api/asgi_application.py").read_text(encoding="utf-8")

        self.assertIn("asyncio.to_thread", source)
        self.assertIn("_run_wsgi_http", source)
        self.assertIn("self.http_host", source)

    def test_lifespan_shutdown_marks_entrypoint_shutdown_controller(self) -> None:
        controller = EntrypointShutdownController()
        host = PlatformAsgiHost(
            state=SimpleNamespace(repository_root=REPO_ROOT),
            shutdown_controller=controller,
        )
        messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            return messages.pop(0)

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        asyncio.run(host({"type": "lifespan"}, receive, send))

        self.assertEqual(
            sent,
            [
                {"type": "lifespan.startup.complete"},
                {"type": "lifespan.shutdown.complete"},
            ],
        )
        self.assertTrue(controller.is_shutting_down())


if __name__ == "__main__":
    unittest.main()
