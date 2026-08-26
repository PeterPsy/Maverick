from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
import unittest

from core.api.http import DEFAULT_MAX_JSON_BODY_BYTES, HttpRequestError, enforce_same_origin_for_unsafe_request, read_json_body, status_line
from core.api.session_api import clear_session_cookie_header, session_cookie_header


class HttpRequestBodyTestCase(unittest.TestCase):
    def test_default_json_body_limit_covers_storage_base64_uploads(self) -> None:
        raw_storage_limit_bytes = 25 * 1024 * 1024
        base64_size = ((raw_storage_limit_bytes + 2) // 3) * 4

        self.assertGreaterEqual(DEFAULT_MAX_JSON_BODY_BYTES, base64_size + 1024 * 1024)

    def test_read_json_body_rejects_declared_body_over_limit(self) -> None:
        environ = {
            "CONTENT_LENGTH": "11",
            "wsgi.input": BytesIO(b"{}"),
        }

        with patch.dict("os.environ", {"MAVERICK_MAX_JSON_BODY_BYTES": "10"}):
            with self.assertRaises(HttpRequestError) as raised:
                read_json_body(environ)

        self.assertEqual(raised.exception.error, "request_body_too_large")
        self.assertEqual(raised.exception.status, "413 Payload Too Large")

    def test_read_json_body_rejects_non_object_json(self) -> None:
        environ = {
            "CONTENT_LENGTH": "2",
            "wsgi.input": BytesIO(b"[]"),
        }

        with self.assertRaises(HttpRequestError) as raised:
            read_json_body(environ)

        self.assertEqual(raised.exception.error, "json_body_must_be_object")
        self.assertEqual(raised.exception.status, "400 Bad Request")

    def test_status_line_names_payload_too_large(self) -> None:
        self.assertEqual(status_line(413), "413 Payload Too Large")

    def test_status_line_names_not_modified(self) -> None:
        self.assertEqual(status_line(304), "304 Not Modified")

    def test_json_responses_default_to_private_no_store(self) -> None:
        from core.api.http import json_response

        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured.update(status=status, headers=dict(headers))

        json_response(start_response, {"authenticated": True})

        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(captured["headers"]["Cache-Control"], "private, no-store")

    def test_json_response_preserves_explicit_cache_policy(self) -> None:
        from core.api.http import json_response

        captured: dict[str, object] = {}
        json_response(
            lambda status, headers: captured.update(status=status, headers=dict(headers)),
            {"revision": "one"},
            headers=[("Cache-Control", "private, no-cache")],
        )

        self.assertEqual(captured["headers"]["Cache-Control"], "private, no-cache")

    def test_cross_origin_unsafe_request_is_forbidden(self) -> None:
        environ = {
            "REQUEST_METHOD": "POST",
            "HTTP_HOST": "maverick.example",
            "HTTP_ORIGIN": "https://evil.example",
        }

        with self.assertRaises(HttpRequestError) as raised:
            enforce_same_origin_for_unsafe_request(environ)

        self.assertEqual(raised.exception.error, "cross_origin_request_forbidden")
        self.assertEqual(raised.exception.status, "403 Forbidden")

    def test_cookie_authenticated_unsafe_request_requires_same_origin_proof(self) -> None:
        environ = {
            "REQUEST_METHOD": "POST",
            "HTTP_HOST": "maverick.example",
            "HTTP_COOKIE": "maverick_session=session-1",
        }

        with self.assertRaises(HttpRequestError) as raised:
            enforce_same_origin_for_unsafe_request(environ)

        self.assertEqual(raised.exception.error, "same_origin_proof_required")
        self.assertEqual(raised.exception.status, "403 Forbidden")

    def test_same_origin_unsafe_request_is_allowed(self) -> None:
        enforce_same_origin_for_unsafe_request(
            {
                "REQUEST_METHOD": "POST",
                "HTTP_HOST": "maverick.example",
                "HTTP_ORIGIN": "https://maverick.example",
            }
        )

    def test_session_cookie_can_be_marked_secure_for_https(self) -> None:
        self.assertIn("Secure", session_cookie_header("session-1", secure=True)[1])
        self.assertIn("Secure", clear_session_cookie_header(secure=True)[1])


if __name__ == "__main__":
    unittest.main()
