from __future__ import annotations

import unittest

from core.egress import (
    DEFAULT_BROWSER_EGRESS_POLICY,
    EgressHop,
    evaluate_browser_egress_url,
    evaluate_browser_redirect_chain,
)
from core.egress.manifest import browser_egress_policy_manifest
from core.egress.networks import METADATA_HOSTS, RESTRICTED_HOSTS, RESTRICTED_NETWORKS


class BrowserEgressPolicyTests(unittest.TestCase):
    def test_policy_uses_shared_manifest_static_targets_and_ranges(self) -> None:
        manifest = browser_egress_policy_manifest()
        admin_targets = {
            (target.scheme, target.host, target.port) for target in DEFAULT_BROWSER_EGRESS_POLICY.admin_dev_targets
        }

        self.assertIn(("http", "hostmachine", 8000), admin_targets)
        self.assertIn(("http", "hostmachine", 8014), admin_targets)
        self.assertEqual(RESTRICTED_HOSTS, frozenset(manifest["restricted_hosts"]))
        self.assertEqual(METADATA_HOSTS, frozenset(manifest["metadata_hosts"]))
        self.assertEqual({str(network) for network in RESTRICTED_NETWORKS}, set(manifest["restricted_networks"]))

    def test_allows_public_http_and_https_after_dns_resolution(self) -> None:
        for url in ("https://example.com/docs", "http://93.184.216.34/"):
            with self.subTest(url=url):
                decision = evaluate_browser_egress_url(url, resolved_addresses=("93.184.216.34",))

                self.assertTrue(decision.allowed)
                self.assertEqual("allowed_public_http", decision.reason)

    def test_blocks_non_http_schemes(self) -> None:
        for url in (
            "file:///etc/passwd",
            "data:text/plain,hello",
            "blob:https://example.com/id",
            "chrome://settings",
            "devtools://devtools/bundled/inspector.html",
            "about:blank",
        ):
            with self.subTest(url=url):
                decision = evaluate_browser_egress_url(url, resolved_addresses=("93.184.216.34",))

                self.assertFalse(decision.allowed)
                self.assertEqual("blocked_disallowed_scheme", decision.reason)

    def test_blocks_loopback_private_link_local_docker_and_metadata_ips(self) -> None:
        blocked_urls = (
            "http://127.0.0.1:8000",
            "http://10.0.0.5",
            "http://169.254.1.10",
            "http://172.17.0.1",
            "http://192.168.1.20",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "http://[fe80::1]/",
            "http://[fd00:ec2::254]/",
        )
        for url in blocked_urls:
            with self.subTest(url=url):
                decision = evaluate_browser_egress_url(url)

                self.assertFalse(decision.allowed)
                self.assertEqual("blocked_restricted_ip", decision.reason)

    def test_blocks_metadata_hostnames_without_dns(self) -> None:
        decision = evaluate_browser_egress_url("http://metadata.google.internal/computeMetadata/v1/")

        self.assertFalse(decision.allowed)
        self.assertEqual("blocked_metadata_host", decision.reason)

    def test_blocks_restricted_hostnames_even_with_public_dns_result(self) -> None:
        blocked_urls = (
            "http://localhost:8000",
            "http://localhost.",
            "http://app.localhost",
            "http://hostmachine:9000",
            "http://host.docker.internal",
            "http://gateway.docker.internal",
        )
        for url in blocked_urls:
            with self.subTest(url=url):
                decision = evaluate_browser_egress_url(url, resolved_addresses=("93.184.216.34",))

                self.assertFalse(decision.allowed)
                self.assertEqual("blocked_restricted_host", decision.reason)

    def test_blocks_ipv6_addresses_with_embedded_restricted_ipv4(self) -> None:
        blocked_urls = (
            "http://[::ffff:127.0.0.1]/",
            "http://[2002:7f00:1::]/",
            "http://[64:ff9b::7f00:1]/",
        )
        for url in blocked_urls:
            with self.subTest(url=url):
                decision = evaluate_browser_egress_url(url)

                self.assertFalse(decision.allowed)
                self.assertEqual("blocked_restricted_ip", decision.reason)

    def test_requires_dns_resolution_for_public_hostnames(self) -> None:
        decision = evaluate_browser_egress_url("https://example.com/")

        self.assertFalse(decision.allowed)
        self.assertEqual("blocked_dns_resolution_required", decision.reason)

    def test_blocks_hostname_when_any_resolved_address_is_restricted(self) -> None:
        decision = evaluate_browser_egress_url(
            "https://example.com/",
            resolved_addresses=("93.184.216.34", "127.0.0.1"),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("blocked_restricted_ip", decision.reason)
        self.assertEqual("127.0.0.1", decision.blocked_address)

    def test_dev_allowlist_requires_admin_enablement(self) -> None:
        denied = evaluate_browser_egress_url("http://hostmachine:8000/apps/base-shell/")
        allowed = evaluate_browser_egress_url(
            "http://hostmachine:8000/apps/base-shell/",
            allow_admin_dev_targets=True,
        )
        allowed_8014 = evaluate_browser_egress_url(
            "http://hostmachine:8014/app/fitness-coach",
            allow_admin_dev_targets=True,
        )
        unsupported_port = evaluate_browser_egress_url(
            "http://hostmachine:9000/app/fitness-coach",
            allow_admin_dev_targets=True,
        )

        self.assertFalse(denied.allowed)
        self.assertEqual("blocked_admin_dev_target_not_enabled", denied.reason)
        self.assertTrue(allowed.allowed)
        self.assertEqual("allowed_admin_dev_target", allowed.reason)
        self.assertTrue(allowed_8014.allowed)
        self.assertEqual("allowed_admin_dev_target", allowed_8014.reason)
        self.assertFalse(unsupported_port.allowed)
        self.assertEqual("blocked_restricted_host", unsupported_port.reason)

    def test_redirect_chain_applies_same_policy_to_every_hop(self) -> None:
        decision = evaluate_browser_redirect_chain(
            (
                EgressHop(url="https://example.com/start", resolved_addresses=("93.184.216.34",)),
                EgressHop(url="http://169.254.169.254/latest/meta-data/"),
            )
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("blocked_restricted_ip", decision.reason)
        self.assertEqual(1, decision.redirect_index)


if __name__ == "__main__":
    unittest.main()
