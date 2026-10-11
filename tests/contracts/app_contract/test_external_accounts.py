"""Shared account declarations remain explicit through contract normalization."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.apps.contract_parser_permissions import parse_permissions_section
from core.apps.contracts import (app_contract_payload, build_app_contract, build_app_permissions,
    build_parsed_app_contract, parse_app_contract_file, write_app_contract_file)
from core.apps.errors import AppContractValidationError
from core.apps.models import AppExternalAccountPermissionDeclaration
from core.apps.service import register_app_source_from_contract
from core.apps.store import AppCollections, AppDocumentStore
from core.shared.in_memory_collection import InMemoryCollection


class ExternalAccountsContractTests(unittest.TestCase):
    def test_personal_capabilities_survive_round_trip(self):
        declaration = AppExternalAccountPermissionDeclaration(["calendar"], ["google-refresh-token"])
        parsed = build_parsed_app_contract(app_id="personal-calendar", name="Calendar", version="1.0.0",
            description="Personal calendar", publisher="test", contract=build_app_contract(
                permissions=build_app_permissions(secret_read=["google-refresh-token"], external_accounts={"google": declaration})))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_app_contract_file(root, parsed)
            loaded = parse_app_contract_file(root)
            store = AppDocumentStore(AppCollections(*(InMemoryCollection() for _ in range(5))))
            source = register_app_source_from_contract(store, source_kind="platform", source_path=str(root))
            restored = store.get_app_source(source.source_id)
        self.assertEqual(loaded.contract.permissions.external_accounts, {"google": declaration})
        self.assertEqual(restored.contract.permissions.external_accounts, {"google": declaration})
        self.assertEqual(app_contract_payload(loaded)["permissions"]["external_accounts"], {
            "google": {"capabilities": ["calendar"], "replaces_secrets": ["google-refresh-token"]}})

    def test_cannot_replace_undeclared_credentials(self):
        with self.assertRaises(AppContractValidationError):
            parse_permissions_section({"external_accounts": {"google": {
                "capabilities": ["gmail"], "replaces_secrets": ["unrelated-secret"]}}})

    def test_invalid_types_and_unknown_fields_are_rejected(self):
        for declaration in ({"capabilities": "gmail"}, {"capabilities": [None]}, {"tokens": True}):
            with self.subTest(declaration=declaration), self.assertRaises(AppContractValidationError):
                parse_permissions_section({"external_accounts": {"google": declaration}})
        with self.assertRaises(AppContractValidationError):
            parse_permissions_section({"secrets": {"read": None}, "external_accounts": {"google": {"replaces_secrets": []}}})

    def test_existing_contracts_without_accounts_keep_their_canonical_shape(self):
        parsed = build_parsed_app_contract(app_id="local-app", name="Local", version="1.0.0", description="Local app", publisher="test")
        self.assertNotIn("external_accounts", app_contract_payload(parsed)["permissions"])
