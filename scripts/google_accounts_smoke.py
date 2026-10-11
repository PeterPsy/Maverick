"""Verify deployed Google OAuth routes without signing in or granting consent."""

import argparse
import json
import re
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, target):
        return None


def check(condition, message):
    if not condition:
        raise RuntimeError(message)
    print("PASS " + message)


def run(origin):
    parsed_origin = urlsplit(origin)
    if (parsed_origin.scheme not in {"https", "http"} or not parsed_origin.hostname
            or parsed_origin.path not in {"", "/"} or parsed_origin.query or parsed_origin.fragment
            or parsed_origin.username or parsed_origin.password):
        raise ValueError("Supply one HTTP(S) platform origin.")
    origin = origin.rstrip("/")
    cookies = CookieJar()
    client = build_opener(NoRedirect(), HTTPCookieProcessor(cookies))

    def request(path, *, body=None, request_origin=None):
        headers = {"Accept": "application/json"}
        if request_origin is not None:
            headers["Origin"] = request_origin
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = client.open(Request(origin + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers), timeout=20)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(1024 * 1024)
            return response.status, {name.lower(): value for name, value in response.headers.items()}, json.loads(raw) if raw else {}

    status, _, provider = request("/api/auth/google/status")
    check(status == 200, "Google provider status is available")
    check({item["id"] for item in provider.get("services", [])} == {"calendar", "gmail", "drive"},
          "Calendar, Gmail and Drive capabilities are advertised")
    status, _, _ = request("/api/connected-accounts")
    check(status == 401, "Personal connections require authentication")
    body = {"mode": "login", "services": []}
    status, _, _ = request("/api/auth/google/start", body=body)
    check(status == 403, "OAuth start rejects a missing Origin")
    status, _, _ = request("/api/auth/google/start", body=body, request_origin="https://untrusted.example")
    check(status == 403, "OAuth start rejects an unrelated Origin")
    if not provider.get("configured"):
        raise RuntimeError("Google is not configured in the running backend. Apply the credential references and callback, then restart.")
    check(True, "Google credential metadata and callback configuration are available")

    # Cancel each flow through the real browser-bound callback, including when a
    # validation fails. No Google account or provider credential is used here.
    for services in ([], ["calendar", "gmail", "drive"]):
        status, headers, started = request("/api/auth/google/start",
            body={"mode": "login", "services": services}, request_origin=origin)
        check(status == 200, "OAuth start accepts " + ("identity-only login" if not services else "all three services"))
        target = urlsplit(started.get("authorization_url", ""))
        params = parse_qs(target.query)
        flow_state = params.get("state", [""])[0]
        try:
            check(target.scheme == "https" and target.netloc == "accounts.google.com"
                  and target.path == "/o/oauth2/v2/auth", "Authorization goes to the Google OAuth endpoint")
            check(params.get("redirect_uri") == [origin + "/api/auth/google/callback"], "OAuth callback matches the deployed platform origin")
            check(params.get("response_type") == ["code"] and params.get("code_challenge_method") == ["S256"]
                  and re.fullmatch(r"[A-Za-z0-9_-]{43}", params.get("code_challenge", [""])[0]),
                  "Authorization uses the code flow and PKCE S256")
            scope = set(params.get("scope", [""])[0].split())
            expected = {"openid", "email", "profile"}
            if services:
                expected.update("https://www.googleapis.com/auth/" + name for name in (
                    "calendar.events", "calendar.calendarlist.readonly", "gmail.modify", "gmail.send", "drive"))
            check(scope == expected, "The request includes exactly the selected scopes")
            cookie = headers.get("set-cookie", "")
            check("HttpOnly" in cookie and "SameSite=Lax" in cookie
                  and (parsed_origin.scheme != "https" or "Secure" in cookie), "OAuth state is bound to a protected browser cookie")
        finally:
            if flow_state:
                callback = "/api/auth/google/callback?" + urlencode({"error": "access_denied", "state": flow_state})
                status, headers, _ = request(callback)
                check(status == 303 and headers.get("location") == "/?google_error=google_consent_cancelled",
                      "Consent cancellation consumes the flow and returns to Maverick")
                status, headers, _ = request(callback)
                check(status == 303 and headers.get("location") == "/?google_error=google_flow_invalid",
                      "A consumed OAuth flow cannot be replayed")
    print("Application checks passed. Google Cloud callback registration and a human-approved login still require an end-to-end check.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="Exact deployed Maverick origin")
    arguments = parser.parse_args()
    try:
        run(arguments.origin)
    except (RuntimeError, ValueError, OSError) as error:
        parser.exit(1, "FAIL " + str(error) + "\n")
