"""Image reads retain scope, byte limits and inert content types."""
import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from actions import perform
from gateway import Gateway, GatewayError


class ImageTests(unittest.TestCase):
    def test_image_route_uses_returned_whatsapp_id_and_exact_scope(self):
        gateway = MagicMock()
        perform(gateway, "messages.image", {"session_id": "phone-1", "chat_id": "123@lid",
                "message_id": "false_123@lid_ABCD", "max_bytes": 2048})
        gateway.read_image.assert_called_once_with(
            "/sessions/phone-1/messages/123%40lid/false_123%40lid_ABCD/media", 2048)
        gateway.request.assert_not_called()

    def test_invalid_scope_and_limits_fail_before_transport(self):
        body = {"session_id": "phone-1", "chat_id": "123@lid", "message_id": "false_123@lid_ABCD"}
        for changes in ({"session_id": "../phone"}, {"chat_id": "123"}, {"message_id": ""},
                        {"max_bytes": 0}, {"max_bytes": 4194305}, {"max_bytes": True}):
            gateway = MagicMock()
            with self.subTest(changes=changes), self.assertRaises(GatewayError):
                perform(gateway, "messages.image", {**body, **changes})
            gateway.read_image.assert_not_called()

    def read(self, content=b"image-bytes", mimetype="image/jpeg", status=200, cap=100):
        response = MagicMock(status=status)
        response.getheader.return_value = mimetype
        response.read.side_effect = lambda size: content[:size]
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch("gateway._connection", return_value=connection):
            try:
                return Gateway("https://example.com", "private-key").read_image(
                    "/sessions/phone/messages/123%40lid/wa-id/media", cap)
            finally:
                connection.close.assert_called_once()
                if response.read.called:
                    response.read.assert_called_once_with(cap + 1)

    def test_returns_bounded_bytes_without_credential(self):
        result = self.read(mimetype="image/jpeg; charset=binary")
        self.assertEqual(base64.b64decode(result["content_base64"]), b"image-bytes")
        self.assertEqual(result["size_bytes"], 11)
        self.assertEqual(result["mimetype"], "image/jpeg")
        self.assertNotIn("private-key", json.dumps(result))

    def test_oversized_empty_and_active_payloads_are_rejected(self):
        for kwargs, status in (({"content": b"x" * 101}, 413), ({"content": b""}, 502),
                               ({"mimetype": "image/svg+xml"}, 415), ({"mimetype": "text/html"}, 415)):
            with self.subTest(kwargs=kwargs), self.assertRaises(GatewayError) as error:
                self.read(**kwargs)
            self.assertEqual(error.exception.status, status)

    def test_errors_preserve_status_without_provider_body(self):
        for status in (401, 403, 404, 429, 503):
            with self.subTest(status=status), self.assertRaises(GatewayError) as error:
                self.read(content=b"private-provider-payload", status=status)
            self.assertEqual(error.exception.status, status)
            self.assertNotIn("private-provider-payload", str(error.exception))

    def test_image_is_declared_on_both_agent_surfaces(self):
        app = Path(__file__).resolve().parents[1]
        cli = json.loads((app / "cli/command_schemas.json").read_text())["commands"]["openwa"]
        self.assertIn("messages.image", cli["argument_schema"]["properties"]["action"]["enum"])
        self.assertEqual(cli["effect_class_by_argument"]["value_effect_classes"]["messages.image"], "read")
        tool = json.loads((app / "mcp/tool_schemas.json").read_text())["tools"]["openwa_messages_image"]
        self.assertEqual(tool["effect_class"], "read")
        self.assertEqual(tool["required_secrets"], ["openwa-api-key"])


if __name__ == "__main__":
    unittest.main()
