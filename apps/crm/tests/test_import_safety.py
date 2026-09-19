"""Import identity, relationship and export fidelity regressions."""

from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))
from service import handle_action
from store import connect
from errors import ValidationError


class ImportSafetyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name

    def call(self, action, **body):
        return handle_action(self.root, "crm." + action, body)[1]

    def apply(self, source, policy="skip"):
        plan = self.call("import_plan", source=source, conflict_policy=policy)
        self.assertTrue(plan["ok"], plan)
        return self.call("import_apply", source=source, conflict_policy=policy, plan_token=plan["plan_token"])

    def test_exact_dedupe_and_conflict_policies(self):
        contact = self.call("create_contact", display_name="Original", email="same@example.test", phone="")['contact']
        source = {"source_id": "one", "entity_type": "contact", "rows": [{"id": "1", "display_name": "Incoming", "email": " SAME@example.test ", "phone": "123"}]}
        self.apply(source, "fill_empty")
        current = self.call("get_record", entity_type="contact", id=contact["id"])["record"]
        self.assertEqual(current["display_name"], "Original")
        self.assertEqual(current["phone"], "123")
        self.assertEqual(len(self.call("export")["export"]["contacts"]), 1)
        source["rows"][0]["display_name"] = "Updated"
        self.apply(source, "overwrite")
        self.assertEqual(self.call("get_record", entity_type="contact", id=contact["id"])["record"]["display_name"], "Updated")
        source["source_id"] = "manual"
        self.assertFalse(self.call("import_plan", source=source, conflict_policy="manual")["ok"])
        source["source_id"] = "separate"
        self.apply(source, "duplicate")
        self.apply(source, "duplicate")
        self.assertEqual(len(self.call("export")["export"]["contacts"]), 2)

    def test_source_mutation_cannot_reuse_plan_and_duplicate_key_is_rejected(self):
        source = {"source_id": "one", "entity_type": "contact", "rows": [{"id": "1", "display_name": "A"}]}
        plan = self.call("import_plan", source=source)
        source["rows"][0]["display_name"] = "B"
        with self.assertRaises(ValidationError):
            self.call("import_apply", source=source, plan_token=plan["plan_token"])
        source["rows"].append({"id": "1", "display_name": "C"})
        self.assertFalse(self.call("import_plan", source=source)["ok"])

    def test_campaigns_custom_objects_and_source_relationship_roundtrip(self):
        source = {"format": "versy", "source_id": "external", "tables": {
            "contacts": [{"id": "person", "full_name": "Person", "company": "Example Ltd"}],
            "real_estate_agencies": [{"id": "agency", "name": "Example Agency"}],
            "property_listings": [{"id": "asset", "title": "Resource", "price": "100"}],
            "outreach_campaigns": [{"id": "campaign", "name": "Campaign"}],
            "outreach_campaign_variants": [{"id": "variant", "campaign_id": "campaign", "name": "A", "message_template": "Hello"}],
            "outreach_campaign_steps": [{"id": "step", "campaign_id": "campaign", "title": "First", "position": 1}],
            "outreach_campaign_enrollments": [{"id": "member", "campaign_id": "campaign", "agency_id": "agency", "variant_id": "variant", "listing_id": "asset"}],
            "outreach_campaign_events": [{"id": "event", "campaign_id": "campaign", "enrollment_id": "member", "summary": "Prepared"}],
            "deals": [{"id": "deal", "name": "Opportunity", "value_cents": 10001, "margin_cents": 4200, "contact_ids": '["person"]'}],
            "data_quality_suggestions": [{"id": "quality", "title": "Review contact", "summary": "Check source evidence", "proposed_changes": '{"type":"send"}'}],
        }}
        result = self.apply(source)
        self.assertTrue(result["committed"])
        exported = self.call("export")["export"]
        self.assertEqual(exported["deals"][0]["value"], 100.01)
        self.assertEqual(exported["deals"][0]["margin_minor"], 4200)
        self.assertTrue(exported["contacts"][0]["account_id"])
        self.assertEqual(exported["workflow_proposals"][0]["status"], "pending")
        self.assertEqual(exported["workflow_proposals"][0]["proposal"]["action"]["type"], "create_task")
        self.assertTrue(self.call("health")["ok"])
        with tempfile.TemporaryDirectory() as target:
            handle_action(target, "crm.import_commit", {"export": exported})
            restored = handle_action(target, "crm.export", {})[1]["export"]
            for table in ("contacts", "campaign_members", "record_links", "custom_object_records", "import_identities"):
                self.assertEqual(len(exported[table]), len(restored[table]), table)
            self.assertTrue(handle_action(target, "crm.health", {})[1]["ok"])

    def test_native_export_preserves_pipeline_stage_tags_and_margin(self):
        pipeline = self.call("create_pipeline", name="Special")["pipeline"]
        stage = self.call("create_pipeline_stage", pipeline_id=pipeline["id"], name="Review", probability=0.5)["stage"]
        deal = self.call("create_deal", name="Custom sales", pipeline_id=pipeline["id"], stage_id=stage["id"], margin_minor=121)["deal"]
        self.call("tag_record", entity_type="deal", id=deal["id"], tag="priority")
        exported = self.call("export")["export"]
        with tempfile.TemporaryDirectory() as target:
            source = {"source_id": "native", "format": "crm_export", "export": exported}
            plan = handle_action(target, "crm.import_plan", {"source": source, "conflict_policy": "overwrite"})[1]
            self.assertTrue(plan["ok"], plan)
            handle_action(target, "crm.import_apply", {"source": source, "conflict_policy": "overwrite", "plan_token": plan["plan_token"]})
            record = handle_action(target, "crm.get_record", {"entity_type": "deal", "id": deal["id"]})[1]["record"]
            self.assertEqual(record["stage_id"], stage["id"])
            self.assertEqual(record["tags"][0]["name"], "priority")
            self.assertEqual(record["margin_minor"], 121)

    def test_provider_selection_is_required_and_cannot_be_spoofed(self):
        contact = self.call("create_contact", display_name="Person")["contact"]
        payload = {"provider_alias": "speech", "crm_entity_type": "contact", "crm_entity_id": contact["id"], "source_entity_type": "transcript", "source_entity_id": "transcript_1", "source_app_id": "unselected-app"}
        with self.assertRaises(ValidationError):
            self.call("link_provider_record", **payload)
        result = self.call("link_provider_record", **payload, _app_dependencies={"dependencies": [{"alias": "speech", "selected_provider_app_ids": ["selected-speech"]}]})
        self.assertEqual(result["external_ref"]["source_app_id"], "selected-speech")
        self.assertEqual(result["external_ref"]["provider_alias"], "speech")

    def test_secret_exclusion_and_sqlite_reader_is_read_only(self):
        path = Path(self.root) / "source.sqlite"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE contacts(id TEXT, full_name TEXT, api_key TEXT)")
            db.execute("INSERT INTO contacts VALUES ('1', 'Person', 'never-copy')")
            db.execute("CREATE TABLE integration_settings(secret TEXT)")
            db.execute("INSERT INTO integration_settings VALUES ('never-copy')")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location("external_sqlite_reader", APP_ROOT / "scripts/read_external_sqlite.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source, excluded = module.read_source(path, "external")
        self.assertIn("integration_settings", excluded)
        self.assertNotIn("never-copy", json.dumps(source))
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
        self.apply(source)
        self.assertNotIn("never-copy", json.dumps(self.call("export")))

    def test_csv_typed_extensions_and_unknown_source_fields_are_preserved(self):
        self.apply({"format": "csv", "source_id": "costs", "entity_type": "expense", "csv": "id,title,amount_minor,currency\n1,Ticket,1250,EUR"})
        self.apply({"source_id": "people", "entity_type": "contact", "rows": [{"display_name": "Person", "favorite_color": "blue"}]})
        exported = self.call("export")["export"]
        self.assertEqual(exported["expenses"][0]["amount_minor"], 1250)
        self.assertEqual(exported["contacts"][0]["metadata"]["import_fields"]["favorite_color"], "blue")

    def test_read_only_plan_does_not_change_database_or_view_state(self):
        self.call("health")
        db_path = Path(self.root) / "crm.sqlite"
        before = db_path.read_bytes()
        state = (Path(self.root) / "view_state.json").read_bytes()
        self.call("import_plan", source={"source_id": "read", "entity_type": "contact", "rows": [{"display_name": "No write"}]})
        self.assertEqual(before, db_path.read_bytes())
        self.assertEqual(state, (Path(self.root) / "view_state.json").read_bytes())
        with connect(self.root) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM import_jobs").fetchone()[0], 0)

    def test_skip_can_be_reconciled_by_later_explicit_overwrite(self):
        contact = self.call('create_contact', display_name='Old', email='same@example.test')['contact']
        source = {'source_id': 'reconcile', 'entity_type': 'contact', 'rows': [{'id': '1', 'display_name': 'New', 'email': 'same@example.test'}]}
        self.apply(source, 'skip')
        self.apply(source, 'overwrite')
        self.assertEqual(self.call('get_record', entity_type='contact', id=contact['id'])['record']['display_name'], 'New')

    def test_export_omits_identity_for_omitted_soft_deleted_record(self):
        self.apply({'source_id': 'deleted', 'entity_type': 'contact', 'rows': [{'id': '1', 'display_name': 'Person'}]})
        contact = self.call('export')['export']['contacts'][0]
        self.call('delete_record', entity_type='contact', id=contact['id'])
        exported = self.call('export')['export']
        self.assertEqual(exported['import_identities'], [])
        with tempfile.TemporaryDirectory() as target:
            handle_action(target, 'crm.import_commit', {'export': exported})
            self.assertTrue(handle_action(target, 'crm.health', {})[1]['ok'])
