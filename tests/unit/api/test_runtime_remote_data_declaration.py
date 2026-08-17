from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeRemoteDataDeclarationApiTest(AppReferenceApiTestSupport, unittest.TestCase):
    def test_plain_hosted_session_rejects_agentic_remote_data_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={
                    "agent_id": "chat",
                    "source_app_id": "chat",
                    "runtime_mode": "plain_hosted_chat",
                    "declared_remote_data_class": "workspace_internal_fake",
                },
                cookie=cookie,
            )

            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "remote_data_declaration_not_applicable")


if __name__ == "__main__":
    unittest.main()
