"""Focused tests for the bounded prompts.chat integration."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


SKILLS_BACKEND = Path(__file__).resolve().parents[1] / "backend"


def load_modules():
    sys.path.insert(0, str(SKILLS_BACKEND))
    for module_name in ("models", "store", "prompts_chat_client", "prompts_chat", "seeds", "service"):
        sys.modules.pop(module_name, None)
    prompts_chat = importlib.import_module("prompts_chat")
    service = importlib.import_module("service")
    return prompts_chat, service


class FakeMcpTransport:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request) -> bytes:
        body = json.loads(request.data.decode("utf-8"))
        tool_name = body["params"]["name"]
        arguments = body["params"]["arguments"]
        self.calls.append((tool_name, arguments))
        envelope = {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(self.payloads[tool_name])}
                ]
            },
        }
        return f"event: message\ndata: {json.dumps(envelope)}\n\n".encode("utf-8")


def remote_payloads() -> dict[str, dict]:
    return {
        "search_skills": {
            "skills": [
                {
                    "id": "remote-skill-1",
                    "slug": "review-helper",
                    "title": "Review Helper",
                    "description": "Review code safely.",
                    "author": "author",
                    "fileNames": ["SKILL.md", "references/checklist.md"],
                }
            ]
        },
        "get_skill": {
            "id": "remote-skill-1",
            "slug": "review-helper",
            "title": "Review Helper",
            "description": "Review code safely.",
            "author": "author",
            "updatedAt": "2026-09-19T10:00:00Z",
            "files": [
                {
                    "filename": "SKILL.md",
                    "content": "---\nname: review-helper\ndescription: Review code safely.\n---\n\n# Review Helper\n\nFollow the checklist.\n",
                },
                {
                    "filename": "references/checklist.md",
                    "content": "# Checklist\n\n- Correctness\n- Security\n",
                },
            ],
        },
    }


class PromptsChatTestCase(unittest.TestCase):
    def test_client_exposes_only_bounded_public_skill_results(self) -> None:
        prompts_chat, _service = load_modules()
        transport = FakeMcpTransport(remote_payloads())
        client = prompts_chat.PromptsChatClient(transport)

        skills = client.search_skills("review", 5)
        skill = client.get_skill("remote-skill-1")

        self.assertEqual(skills["skills"][0]["files"], ["SKILL.md", "references/checklist.md"])
        self.assertEqual(len(skill["content_sha256"]), 64)
        self.assertEqual([name for name, _arguments in transport.calls], [
            "search_skills",
            "get_skill",
        ])
        with self.assertRaisesRegex(prompts_chat.PromptsChatError, "limit must be between"):
            client.search_skills("code review", 0)

    def test_transport_refuses_remote_mutation_tools(self) -> None:
        prompts_chat, _service = load_modules()
        transport = FakeMcpTransport(remote_payloads())
        client = prompts_chat.PublicPromptsChatMcpClient(transport)

        with self.assertRaisesRegex(prompts_chat.PromptsChatError, "public read operations"):
            client.call("save_skill", {})

        self.assertEqual(transport.calls, [])

    def test_service_requires_digest_bound_confirmation_and_installs_all_files(self) -> None:
        prompts_chat, service = load_modules()
        client = prompts_chat.PromptsChatClient(FakeMcpTransport(remote_payloads()))
        remote_skill = client.get_skill("remote-skill-1")
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "skills"

            denied_status, denied = service.handle_action(
                data_root,
                {"action": "prompts_chat.install_skill", "remote_id": "remote-skill-1"},
                prompts_chat_client=client,
            )
            stale_status, stale = service.handle_action(
                data_root,
                {
                    "action": "prompts_chat.install_skill",
                    "remote_id": "remote-skill-1",
                    "confirmed": True,
                    "expected_content_sha256": "0" * 64,
                },
                prompts_chat_client=client,
            )
            status, payload = service.handle_action(
                data_root,
                {
                    "action": "prompts_chat.install_skill",
                    "remote_id": "remote-skill-1",
                    "confirmed": True,
                    "expected_content_sha256": remote_skill["content_sha256"],
                },
                prompts_chat_client=client,
            )

            self.assertEqual(denied_status, 409)
            self.assertEqual(denied["error"], "prompts_chat_confirmation_required")
            self.assertEqual(stale_status, 409)
            self.assertEqual(stale["error"], "prompts_chat_confirmation_stale")
            self.assertEqual(status, 200)
            self.assertEqual(payload["skill"]["id"], "review-helper")
            self.assertEqual(payload["skill"]["origin"], "prompts.chat")
            self.assertEqual(payload["skill"]["remote_id"], "remote-skill-1")
            self.assertEqual(payload["skill"]["source_url"], remote_skill["link"])
            self.assertEqual(payload["skill"]["source_content_sha256"], remote_skill["content_sha256"])
            self.assertEqual(payload["installed_files"], ["SKILL.md", "references/checklist.md"])
            self.assertEqual(
                (data_root / "skills" / "review-helper" / "references" / "checklist.md").read_text(encoding="utf-8"),
                "# Checklist\n\n- Correctness\n- Security\n",
            )
            self.assertEqual(
                service.app_events_for_action("prompts_chat.install_skill"),
                [{"type": "maverick.app.data-changed", "resource": "skills"}],
            )

            delete_status, delete_payload = service.handle_action(
                data_root,
                {"action": "delete_skill", "skill_id": "review-helper"},
            )
            self.assertEqual(delete_status, 200)
            self.assertEqual(delete_payload, {"deleted": True})
            self.assertFalse((data_root / "skills" / "review-helper").exists())

    def test_remote_skill_rejects_unsafe_paths_before_install(self) -> None:
        prompts_chat, _service = load_modules()
        payloads = remote_payloads()
        payloads["get_skill"]["files"].append({"filename": "../escape.md", "content": "escape"})
        client = prompts_chat.PromptsChatClient(FakeMcpTransport(payloads))

        with self.assertRaisesRegex(prompts_chat.PromptsChatError, "unsafe file path"):
            client.get_skill("remote-skill-1")

    def test_remote_skill_rejects_conflicting_paths_before_install(self) -> None:
        prompts_chat, _service = load_modules()
        payloads = remote_payloads()
        payloads["get_skill"]["files"].extend(
            [
                {"filename": "references", "content": "not a directory"},
                {"filename": "references/example.md", "content": "nested"},
            ]
        )
        client = prompts_chat.PromptsChatClient(FakeMcpTransport(payloads))

        with self.assertRaisesRegex(prompts_chat.PromptsChatError, "conflicting file paths"):
            client.get_skill("remote-skill-1")

    def test_install_does_not_replace_a_workspace_skill(self) -> None:
        prompts_chat, service = load_modules()
        client = prompts_chat.PromptsChatClient(FakeMcpTransport(remote_payloads()))
        remote_skill = client.get_skill("remote-skill-1")
        request = {
            "action": "prompts_chat.install_skill",
            "remote_id": "remote-skill-1",
            "confirmed": True,
            "expected_content_sha256": remote_skill["content_sha256"],
        }
        with tempfile.TemporaryDirectory() as temp:
            data_root = Path(temp) / "skills"
            first_status, _first = service.handle_action(data_root, request, prompts_chat_client=client)
            second_status, second = service.handle_action(data_root, request, prompts_chat_client=client)

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 409)
        self.assertEqual(second["error"], "skill_already_exists")


if __name__ == "__main__":
    unittest.main()
