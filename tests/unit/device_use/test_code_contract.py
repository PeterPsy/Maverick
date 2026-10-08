import unittest

from core.api.device_use_reconnection import _renewable_contract
from core.device_use.contract import (
    DEVICE_USE_EXECUTOR_CONTRACT, DEVICE_USE_TOOL_CONTRACT_DIGEST,
    device_use_dynamic_tools, device_use_instructions,
)
from core.device_use.invocation_deadline import invocation_timeout_seconds
from types import SimpleNamespace
from core.device_use.service import _validate_text_result
from core.device_use.result_facts import native_result_facts
from core.device_use.errors import DeviceUseAuthorizationError
import json


class MacCodeContractTests(unittest.TestCase):
    def test_code_tool_has_file_and_owned_process_lifecycle(self):
        tool = next(item for item in device_use_dynamic_tools() if item["name"] == "mac_code")
        properties = tool["inputSchema"]["properties"]
        self.assertEqual(properties["stdout_offset"]["minimum"], 0)
        self.assertEqual(properties["wait_ms"]["maximum"], 10000)
        for action in ("resume_project", "read_file", "write_file", "replace_text", "run_command",
                       "read_process", "write_stdin", "stop_process", "revoke_project", "select_project"):
            self.assertIn(action, properties["action"]["enum"])
        self.assertNotIn("environment", properties)

    def test_full_guidance_distinguishes_mac_shell_from_server_and_folder_sandbox(self):
        full = device_use_instructions(mode="full", approved_apps=(), initial_app="com.apple.Finder")
        self.assertIn("mac_code", full)
        self.assertIn("cwd is not a security sandbox", full)
        self.assertIn("turn completion", full)
        self.assertIn("expected_sha256", full)
        bounded = device_use_instructions(mode="on", approved_apps=("com.apple.Finder",), initial_app="com.apple.Finder")
        self.assertNotIn("For files, coding and installations on the user's Mac use mac_code", bounded)

    def test_full_files_and_commands_do_not_require_a_folder_grant(self):
        full = device_use_instructions(mode="full", approved_apps=(), initial_app="com.apple.Finder")
        self.assertIn("no folder grant, project_id, resume_project or picker is required", full)
        self.assertNotIn("authorize_project opens one native folder picker", full)
        self.assertNotIn("Project IDs never grant access outside the user-picked folder", full)
        code = next(item for item in device_use_dynamic_tools() if item["name"] == "mac_code")
        self.assertEqual(code["inputSchema"]["required"], ["action"])
        self.assertIn("Absolute paths", code["description"])
        self.assertNotIn("authorize_project", code["inputSchema"]["properties"]["action"]["enum"])
        media = next(item for item in device_use_dynamic_tools() if item["name"] == "mac_project")
        self.assertIn("directory", media["inputSchema"]["properties"])
        steps = media["inputSchema"]["properties"]["steps"]["items"]["properties"]
        self.assertNotIn("directory", steps)
        self.assertNotIn("choose_directory", steps)

    def test_reviewed_v50_reconnects_to_full_file_contract(self):
        old = SimpleNamespace(executor_contract="macos-v50", tool_contract_digest="4dd7bf89e6dd520294199f7b997e9388debf6004aaa6f618715033b77ed4b238")
        current = SimpleNamespace(executor_contract=DEVICE_USE_EXECUTOR_CONTRACT, tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST)
        self.assertTrue(_renewable_contract(old, current))

    def test_reviewed_v47_reconnects_without_accepting_unknown_contracts(self):
        current = SimpleNamespace(executor_contract=DEVICE_USE_EXECUTOR_CONTRACT,
                                  tool_contract_digest=DEVICE_USE_TOOL_CONTRACT_DIGEST)
        old = SimpleNamespace(executor_contract="macos-v47",
                              tool_contract_digest="d0405d09ac1ff6903336a7fa7427c7c28e2922167a0dfe302a4db0bc48b00c71")
        self.assertTrue(_renewable_contract(old, current))
        old.tool_contract_digest = "a" * 64
        self.assertFalse(_renewable_contract(old, current))

    def test_picker_budget_is_separate_from_short_process_wire_calls(self):
        self.assertEqual(invocation_timeout_seconds("mac_code", "select_project"), 300)
        self.assertEqual(invocation_timeout_seconds("mac_code", "run_command"), 180)
        self.assertEqual(invocation_timeout_seconds("mac_code", "read_process"), 180)

    def test_code_can_contain_literal_image_urls_without_admitting_ui_text_images(self):
        result = {"success": True, "contentItems": [{"type": "inputText", "text": 'const icon = "data:image/png;base64,...";'}]}
        _validate_text_result(result, allows_code_text=True)
        with self.assertRaises(DeviceUseAuthorizationError):
            _validate_text_result(result)

    def test_command_transport_success_does_not_claim_successful_exit(self):
        for state, code, expected in [("running", None, None), ("exited", 0, True),
                                      ("exited", 7, False), ("timed_out", 124, False)]:
            facts = native_result_facts({"success": True, "contentItems": [{"text": json.dumps(
                {"action": "read_process", "state": state, "exit_code": code})}]})
            self.assertEqual(facts["result_valid"], expected)
