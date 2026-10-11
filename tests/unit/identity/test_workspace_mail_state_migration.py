"""Workspace IMAP mail survives the switch to personal Google app roots."""

from pathlib import Path
import tempfile
import unittest

from core.app_sdk.account_state import migrate_account_state
from tests.unit.identity import test_account_state_migration as fixtures


class WorkspaceMailStateMigrationTests(unittest.TestCase):
    run_app = fixtures.AccountStateMigrationTests.run_app

    def test_mail_restores_only_imap_cache_and_rebuilds_scoped_credential_metadata(self):
        self.run_app("mail", '''
import tempfile
from pathlib import Path
from connections import prepare_imap_smtp
from platform_account import attach_platform_account
from database import connect, ensure_schema, db_path
with tempfile.TemporaryDirectory() as scratch:
    source = Path(scratch) / "workspace-mail"
    ensure_schema(source)
    connection_id = prepare_imap_smtp(source, {"email_address": "team@example.com", "_workspace_id": "second"})["connection_id"]
    with connect(source) as db:
        db.execute("UPDATE connections SET status='connected' WHERE id=?", (connection_id,))
        db.execute("INSERT INTO connections(id,provider,email_address,display_name,status,created_at,updated_at) VALUES ('shared-google','gmail','other@example.com','Other','connected','now','now')")
        for connection, prefix in [(connection_id, 'imap'), ('shared-google', 'google')]:
            db.execute("INSERT INTO threads(id,connection_id,provider_thread_id,subject,last_message_at,updated_at) VALUES (?,?,?,?,?,?)", (prefix+'-thread',connection,'remote',prefix+' subject','now','now'))
            db.execute("INSERT INTO messages(id,thread_id,provider_message_id,sender_json,sent_at,body_text) VALUES (?,?,?,?,?,?)", (prefix+'-message',prefix+'-thread','remote','{}','now',prefix+' retained body'))
            db.execute("INSERT INTO attachments(id,message_id,provider_attachment_id,filename,created_at,updated_at) VALUES (?,?,?,?,?,?)", (prefix+'-attachment',prefix+'-message','remote',prefix+'.pdf','now','now'))
            db.execute("INSERT INTO drafts(id,connection_id,subject,body_text,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (prefix+'-draft',connection,prefix+' subject','Original','draft','now','now'))
            db.execute("INSERT INTO entity_links(id,source_entity_type,source_entity_id,target_app_id,target_entity_type,target_entity_id,relation,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (prefix+'-link','email_thread',prefix+'-thread','memory','node',prefix+'-node','related','now','now'))
            db.execute("INSERT INTO send_confirmations(id,draft_id,token_hash,snapshot_hash,created_at,expires_at) VALUES (?,?,?,?,?,?)", (prefix+'-approval',prefix+'-draft',prefix+'-token','snapshot','now','later'))
        db.execute("UPDATE provider_credentials SET metadata_json=?", ('{"untrusted":"do-not-import"}',))
    original = db_path(source).read_bytes()
    root = source / "connected-accounts" / "owner" / "shared"
    payload = {"data_root": str(root), "workspace_data_root": str(source), "workspace_id": "second", "app_secrets": {"mailbox-password": "existing-test-authority"}, "external_accounts": [{"account_id": "google_personal", "provider": "google", "email": "owner@example.com", "display_name": "Owner", "services": ["gmail"], "access_handle": "test-handle"}]}
    attach_platform_account(payload)
    assert payload["app_secrets"]["mailbox-password"] == "existing-test-authority"
    with connect(root) as db:
        assert {r[0] for r in db.execute("SELECT id FROM connections")} == {connection_id, "platform_google_personal"}
        for table, identifier in [('threads','imap-thread'), ('messages','imap-message'), ('attachments','imap-attachment'), ('drafts','imap-draft'), ('entity_links','imap-link')]:
            assert [r[0] for r in db.execute('SELECT id FROM '+table)] == [identifier], table
        assert db.execute("SELECT count(*) FROM send_confirmations").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM oauth_credentials").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM mail_fts WHERE mail_fts MATCH 'retained'").fetchone()[0] == 1
        credential = db.execute("SELECT * FROM provider_credentials").fetchone()
        assert credential['resource_id'] == connection_id
        assert credential['logical_name'] == 'mailbox-password'
        assert 'second' in credential['grant_id']
        assert 'untrusted' not in credential['metadata_json']
        db.execute("UPDATE drafts SET body_text='Later edit' WHERE id='imap-draft'")
        db.execute("UPDATE connections SET status='disconnected' WHERE id=?", (connection_id,))
    attach_platform_account(payload)
    with connect(root) as db:
        assert db.execute("SELECT body_text FROM drafts").fetchone()[0] == 'Later edit'
        assert db.execute("SELECT status FROM connections WHERE id=?", (connection_id,)).fetchone()[0] == 'disconnected'
    assert db_path(source).read_bytes() == original
''')

    def test_workspace_import_is_opt_in_once_and_retries_failed_migrations(self):
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch)
            root = source / "connected-accounts" / "owner" / "shared"
            payload = {"data_root": str(root), "workspace_data_root": str(source), "external_accounts": []}
            calls = []
            migrate_account_state(payload, lambda *args: self.fail("No personal source expected"))
            def failing(*args):
                raise RuntimeError("retry")
            with self.assertRaises(RuntimeError):
                migrate_account_state(payload, None, migrate_workspace=failing)
            for _ in range(2):
                migrate_account_state(payload, None, migrate_workspace=lambda *args: calls.append(args))
            self.assertEqual(calls, [(source, root)])

    def test_rejects_other_workspace_and_symlink_sources_before_import(self):
        with tempfile.TemporaryDirectory() as scratch:
            workspace = Path(scratch) / "workspace"
            other = Path(scratch) / "other"
            workspace.mkdir()
            other.mkdir()
            root = workspace / "connected-accounts" / "owner" / "shared"
            payload = {"data_root": str(root), "workspace_data_root": str(other), "external_accounts": []}
            with self.assertRaises(ValueError):
                migrate_account_state(payload, None, migrate_workspace=lambda *args: self.fail("Forbidden import"))
            self.assertFalse(root.exists())
            (workspace / "connected-accounts").symlink_to(other, target_is_directory=True)
            payload["workspace_data_root"] = str(workspace)
            with self.assertRaises(ValueError):
                migrate_account_state(payload, None, migrate_workspace=lambda *args: self.fail("Symlink import"))
