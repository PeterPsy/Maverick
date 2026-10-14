"""Browser origin proof must fail closed without trusting proxy headers."""

import unittest

from core.api.http import HttpRequestError, enforce_same_origin_for_unsafe_request


class HttpOriginTest(unittest.TestCase):
    def request(self, **headers):
        return {
            "REQUEST_METHOD": "POST",
            "HTTP_HOST": "loopino.test",
            "wsgi.url_scheme": "https",
            "HTTP_COOKIE": "loopino_session=synthetic",
            **headers,
        }

    def assert_denied(self, environ):
        with self.assertRaises(HttpRequestError) as raised:
            enforce_same_origin_for_unsafe_request(environ)
        self.assertEqual(raised.exception.status, "403 Forbidden")

    def test_invalid_origin_cannot_fall_back_to_valid_referer(self):
        for origin in (
            "null", "", "not-a-url", "//loopino.test", "https://",
            "https://[broken", "https://loopino.test:bad", "https://loopino.test:65536",
            "https://user@loopino.test", "https://loopino.test/path",
            "https://loopino.test/", "https://loopino.test:",
            "https://loopino.test?", "https://loopino.test#",
            "https://loopino.test?query", "https://loopino.test#fragment",
            "https://loopino.\ttest", "https://loopino.test\\path",
        ):
            with self.subTest(origin=origin):
                self.assert_denied(self.request(
                    HTTP_ORIGIN=origin, HTTP_REFERER="https://loopino.test/app",
                ))

    def test_scheme_host_and_effective_port_must_match(self):
        for origin in ("http://loopino.test", "https://other.test", "https://loopino.test:444"):
            with self.subTest(origin=origin):
                self.assert_denied(self.request(HTTP_ORIGIN=origin))
        for origin in ("https://loopino.test", "https://LOOPINO.test:443"):
            with self.subTest(origin=origin):
                enforce_same_origin_for_unsafe_request(self.request(HTTP_ORIGIN=origin))

    def test_nondefault_port_and_ipv6(self):
        enforce_same_origin_for_unsafe_request(self.request(
            HTTP_HOST="[::1]:8443", HTTP_ORIGIN="https://[::1]:8443",
        ))
        self.assert_denied(self.request(HTTP_HOST="loopino.test:8443", HTTP_ORIGIN="https://loopino.test"))

    def test_referer_is_allowed_only_when_origin_is_absent(self):
        enforce_same_origin_for_unsafe_request(self.request(HTTP_REFERER="https://loopino.test/app?tab=one"))
        for referer in ("null", "/app", "https://foreign.test/app", "http://loopino.test/app"):
            with self.subTest(referer=referer):
                self.assert_denied(self.request(HTTP_REFERER=referer))

    def test_missing_or_invalid_request_authority_fails_closed(self):
        for headers in (
            {"HTTP_HOST": ""}, {"HTTP_HOST": "loopino.test/path"},
            {"HTTP_HOST": "user@loopino.test"}, {"wsgi.url_scheme": ""},
        ):
            with self.subTest(headers=headers):
                self.assert_denied(self.request(HTTP_ORIGIN="https://loopino.test", **headers))

    def test_raw_forwarded_headers_cannot_supply_origin_authority(self):
        self.assert_denied(self.request(
            **{"wsgi.url_scheme": "http"}, HTTP_ORIGIN="https://loopino.test",
            HTTP_X_FORWARDED_PROTO="https", HTTP_FORWARDED="proto=https;host=loopino.test",
        ))
        enforce_same_origin_for_unsafe_request(self.request(
            HTTP_ORIGIN="https://loopino.test", HTTP_X_FORWARDED_PROTO="http",
        ))

    def test_cookie_requests_without_proof_are_denied_but_nonbrowser_calls_remain_supported(self):
        self.assert_denied(self.request())
        enforce_same_origin_for_unsafe_request(self.request(HTTP_COOKIE=""))
        for method in ("GET", "HEAD", "OPTIONS"):
            enforce_same_origin_for_unsafe_request(self.request(REQUEST_METHOD=method))
