from __future__ import annotations

import unittest

from core.runtime.output_compaction.raw_payload import collect_raw_text_fields, sanitize_raw_payload
from core.runtime.output_compaction.redaction import redact_text


class RuntimeOutputRedactionTest(unittest.TestCase):
    def test_redact_text_covers_headers_query_env_jwt_keys_and_url_credentials(self) -> None:
        raw = "\n".join(
            [
                "Authorization: Bearer secret-bearer-value",
                "Cookie: session=abc; csrf=def",
                "GET https://example.test/path?access_token=secret-token&ok=1",
                "APP_API_KEY=secret-api-key",
                "DATABASE_URL=https://user:pass@example.test/db",
                "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.signatureValue",
                "sk-secretOpenAIStyleKey123456",
                "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----",
            ]
        )

        redacted = redact_text(raw)

        self.assertNotIn("secret-bearer-value", redacted)
        self.assertNotIn("session=abc", redacted)
        self.assertNotIn("secret-token", redacted)
        self.assertNotIn("secret-api-key", redacted)
        self.assertNotIn("user:pass", redacted)
        self.assertNotIn("eyJhbGci", redacted)
        self.assertNotIn("secretOpenAIStyleKey", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertIn("<redacted>", redacted)

    def test_sanitize_raw_payload_removes_large_provider_text_and_redacts_sensitive_keys(self) -> None:
        raw = {
            "type": "item.completed",
            "item": {
                "id": "cmd-1",
                "type": "commandExecution",
                "command": "pytest",
                "aggregatedOutput": "Authorization: Bearer secret\n" + ("noise\n" * 400),
                "metadata": {"api_key": "secret-key"},
            },
        }

        result = sanitize_raw_payload(raw, omit_text_threshold_bytes=100)

        self.assertIsNotNone(result.raw)
        sanitized = dict(result.raw or {})
        self.assertTrue(sanitized["has_omitted_provider_payload"])
        self.assertIn("raw.item.aggregatedOutput", result.omitted_fields)
        self.assertNotIn("aggregatedOutput", sanitized["item"])
        self.assertEqual(sanitized["item"]["metadata"]["api_key"], "<redacted>")
        self.assertEqual(sanitized["item_type"], "commandExecution")

    def test_sanitize_raw_payload_skips_omitted_list_items(self) -> None:
        raw = {"items": [{"text": "x" * 200}, {"type": "kept"}]}

        result = sanitize_raw_payload(raw, omit_text_threshold_bytes=20)

        self.assertEqual(result.raw, {"items": [{"type": "kept"}], "has_omitted_provider_payload": True, "omitted_provider_payload_fields": ("raw.items[0].text",)})

    def test_collect_raw_text_fields_finds_nested_aggregated_output(self) -> None:
        raw = {"item": {"aggregatedOutput": "x" * 1200, "type": "commandExecution"}}

        fields = collect_raw_text_fields(raw)

        self.assertEqual(fields, (("raw.item.aggregatedOutput", "x" * 1200),))


if __name__ == "__main__":
    unittest.main()
