"""Focused tests for hosted browser-origin health probes."""

from __future__ import annotations

from io import BytesIO
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from core.shared.installer_tls import hosted_browser_origin_is_healthy


class HostedBrowserOriginHealthTests(unittest.TestCase):
    def test_accepts_only_the_expected_session_error_for_each_origin_kind(self) -> None:
        cases = (
            ("session_required", "session_required", True),
            ("app_frame_session_required", "app_frame_session_required", True),
            ("session_required", "app_frame_session_required", False),
            ("app_frame_session_required", "session_required", False),
            ("another_unauthorized_error", "session_required", False),
        )
        for response_error, expected_error, healthy in cases:
            with self.subTest(response_error=response_error, expected_error=expected_error):
                exception = HTTPError(
                    "https://reserved.example.test/",
                    401,
                    "Unauthorized",
                    hdrs=None,
                    fp=BytesIO(json.dumps({"error": response_error}).encode("utf-8")),
                )
                with patch("core.shared.installer_tls.request.urlopen", side_effect=exception):
                    self.assertEqual(
                        hosted_browser_origin_is_healthy(
                            "https://reserved.example.test/",
                            timeout_seconds=1.0,
                            expected_error=expected_error,
                        ),
                        healthy,
                    )

    def test_rejects_an_unexpected_success_response(self) -> None:
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch("core.shared.installer_tls.request.urlopen", return_value=response):
            self.assertFalse(
                hosted_browser_origin_is_healthy(
                    "https://reserved.example.test/",
                    timeout_seconds=1.0,
                    expected_error="session_required",
                )
            )


if __name__ == "__main__":
    unittest.main()
