"""A interrupted DNS job must preserve mail and tolerate selective restoration."""

from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from core.installation.cloudflare import dns_changes
from core.installation.dns_transaction import apply_dns, restore_dns
from core.installation.errors import InstallationError


class Provider:
    def __init__(self, records):
        self.inventory = deepcopy(records)
        self.counter = 100
        self.fail_next = False

    def zone(self, host):
        return {"id": "a" * 32, "status": "active"}

    def records(self, zone):
        return deepcopy(self.inventory)

    def create(self, zone, record):
        if self.fail_next:
            self.fail_next = False
            raise OSError("Interrupted after deletion")
        self.counter += 1
        result = {**record, "id": str(self.counter)}
        self.inventory.append(result)
        return result

    def delete(self, zone, identifier):
        self.inventory = [item for item in self.inventory if item["id"] != identifier]


class DnsTransactionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.private = Path(self.folder.name)
        self.mail = {"id": "mail", "name": "example.com", "type": "MX", "content": "mail.example.com", "ttl": 300, "priority": 10}
        self.before = [{"id": "one", "name": "maverick.example.com", "type": "A", "content": "1.1.1.1", "ttl": 300, "proxied": False}, self.mail]
        self.provider = Provider(self.before)
        self.service = SimpleNamespace(secret_store=None, dns_factory=lambda *a, **kw: self.provider)
        self.job = {"job_id": "b" * 32, "actor_user_id": "admin"}
        self.plan = {"hostname": "maverick.example.com", "target_ip": "8.8.8.8", "dns_secret_ref": "platform:secret-alias/test-token",
                     "zone": {"id": "a" * 32}, "dns_changes": dns_changes("maverick.example.com", "8.8.8.8", self.before)}

    def tearDown(self):
        self.folder.cleanup()

    def test_retry_after_delete_recovers_and_rollback_is_repeatable(self):
        self.provider.fail_next = True
        with self.assertRaises(OSError):
            apply_dns(self.service, self.job, self.plan, self.private)
        apply_dns(self.service, self.job, self.plan, self.private)
        apply_dns(self.service, self.job, self.plan, self.private)
        self.assertEqual(len(self.provider.inventory), 3)
        self.assertIn(self.mail, self.provider.inventory)
        restore_dns(self.service, self.job, self.plan, self.private)
        restore_dns(self.service, self.job, self.plan, self.private)
        self.assertEqual(len(self.provider.inventory), 2)
        self.assertIn(self.mail, self.provider.inventory)
        self.assertEqual(next(item for item in self.provider.inventory if item['type'] == 'A')['content'], '1.1.1.1')

    def test_rollback_rejects_records_edited_by_another_actor(self):
        apply_dns(self.service, self.job, self.plan, self.private)
        self.provider.inventory[1]['comment'] = 'Edited by another admin'
        with self.assertRaises(InstallationError):
            restore_dns(self.service, self.job, self.plan, self.private)

    def test_wildcard_cannot_bypass_an_existing_txt_node_or_wrong_ipv6(self):
        wildcard = {"type": "A", "name": "*.example.com", "content": "8.8.8.8", "proxied": False}
        for obstruction in [{"type": "TXT", "name": "maverick.example.com"},
                            {"type": "TXT", "name": "nested.maverick.example.com"},
                            {"type": "AAAA", "name": "*.example.com", "content": "2606:4700::1111"}]:
            with self.subTest(obstruction=obstruction):
                changes = dns_changes('maverick.example.com', '8.8.8.8', [wildcard, obstruction])
                self.assertEqual(changes[0]['action'], 'create')

    def test_plan_that_promised_no_mutation_cannot_silently_create_records(self):
        wildcard = {'id': 'wildcard', 'name': '*.example.com', 'type': 'A', 'content': '8.8.8.8', 'ttl': 300, 'proxied': False}
        self.plan['dns_changes'] = dns_changes(self.plan['hostname'], self.plan['target_ip'], [wildcard])
        self.provider.inventory = [{**wildcard, 'content': '1.1.1.1'}, self.mail]
        before = deepcopy(self.provider.inventory)
        with self.assertRaisesRegex(InstallationError, 'dns_records_changed_since_plan'):
            apply_dns(self.service, self.job, self.plan, self.private)
        self.assertEqual(self.provider.inventory, before)
