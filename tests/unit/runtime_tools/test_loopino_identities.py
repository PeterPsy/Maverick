"""Fresh token and provider alias identities reject predecessor contracts."""

import base64
import json
import re
import unittest
from unittest.mock import patch

from core.runtime.tool_schema import provider_tool_name
from core.runtime.workspace_api_token import TOKEN_VERSION, issue_workspace_api_token, verify_workspace_api_token
from tests.support.env import apply_test_environment_defaults


class LoopinoRuntimeIdentityTests(unittest.TestCase):
    def test_fresh_token_verifies_and_signed_predecessor_version_is_rejected(self):
        apply_test_environment_defaults()
        token = issue_workspace_api_token(workspace_id="default", runtime_session_id="session-identity")
        encoded = token.split(".")[0]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        self.assertEqual(payload["version"], "loopino.runtime-api-token.v2")
        self.assertEqual(verify_workspace_api_token(token)["runtime_session_id"], "session-identity")
        with patch("core.runtime.workspace_api_token.TOKEN_VERSION", "mvr3rt2"):
            predecessor = issue_workspace_api_token(workspace_id="default", runtime_session_id="session-identity")
        self.assertIsNone(verify_workspace_api_token(predecessor))
        self.assertEqual(TOKEN_VERSION, "loopino.runtime-api-token.v2")

    def test_aliases_preserve_length_character_and_truncation_uniqueness_contracts(self):
        handles = ["mcp:" + "a" * 100 + suffix for suffix in ("1", "2")]
        aliases = [provider_tool_name(handle) for handle in handles]
        self.assertNotEqual(*aliases)
        for handle, alias in zip(handles, aliases):
            self.assertTrue(alias.startswith("loopino_"))
            self.assertLessEqual(len(alias), 64)
            self.assertTrue(re.fullmatch(r"[a-zA-Z0-9_]+", alias))
            self.assertEqual(provider_tool_name(handle), alias)
