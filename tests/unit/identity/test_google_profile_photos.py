"""Photos stay scoped to the verified Google subject and contain no authority."""
from dataclasses import replace
from datetime import timedelta
import unittest
from unittest.mock import patch
from core.app_sdk.google_profile import google_picture_url
from core.connected_accounts.profile import refresh_profile
from core.connected_accounts.service import complete_flow, public_account
from tests.support import connected_account_fixture as fixtures

PICTURE = 'https://lh3.googleusercontent.com/a/photo=s96-c'

class GoogleProfilePhotoTests(unittest.TestCase):
    setUp = fixtures.ConnectedAccountFixture.setUp
    flow = fixtures.ConnectedAccountFixture.flow
    complete = fixtures.ConnectedAccountFixture.complete

    def account(self):
        query, browser = self.flow(['calendar'])
        return self.complete(query, browser, scopes=['profile'])[1]

    def test_only_bounded_google_https_picture_urls_are_accepted(self):
        self.assertEqual(google_picture_url(PICTURE), PICTURE)
        for value in (None, 'http://lh3.googleusercontent.com/a', 'https://googleusercontent.com.evil.test/a',
                      'https://evil.test/a', 'https://user@lh3.googleusercontent.com/a', 'data:image/svg+xml,x',
                      'https://lh3.googleusercontent.com:8080/a', 'https://lh3.googleusercontent.com/a#fragment',
                      'https://lh3.googleusercontent.com/\\evil', 'https://lh3.googleusercontent.com/' + 'x' * 4096):
            self.assertEqual(google_picture_url(value), '', value)

    def test_verified_oauth_picture_is_persisted_and_public(self):
        query, browser = self.flow(['calendar'])
        _, account, _, _ = complete_flow(self.state, raw_state=query['state'][0], browser=browser,
            code='auth-code', context=self.context, now=self.now,
            exchange=lambda *args, **kwargs: {'id_token': 'signed-token', 'scope': 'profile', 'refresh_token': 'private'},
            identity_verifier=lambda *args, **kwargs: {'sub': 'subject-alice', 'email': 'alice@example.com', 'picture': PICTURE})
        self.assertEqual(self.accounts.get_account(account.account_id).picture_url, PICTURE)
        self.assertEqual(public_account(account)['picture_url'], PICTURE)

    def test_hydrates_existing_profile_once_without_exposing_credentials(self):
        account = self.account()
        with patch('core.connected_accounts.google.json_request', side_effect=[
                {'access_token': 'private-access'}, {'sub': account.subject, 'picture': PICTURE}]) as request:
            updated = refresh_profile(account, account_store=self.accounts, secret_store=self.secrets, now=self.now)
            cached = refresh_profile(updated, account_store=self.accounts, secret_store=self.secrets, now=self.now)
        self.assertEqual(updated.picture_url, PICTURE)
        self.assertEqual(cached, updated)
        self.assertEqual(request.call_count, 2)
        public = public_account(updated)
        self.assertEqual(public['picture_url'], PICTURE)
        self.assertNotIn('private', repr(public))
        self.assertNotIn('private-access', repr(self.accounts.collections.accounts.find({})))

    def test_missing_or_mismatched_profiles_back_off_without_changing_identity(self):
        for profile in ({'sub': 'another-user', 'picture': PICTURE}, {'sub': 'subject-alice'}):
            account = self.account()
            with patch('core.connected_accounts.google.json_request', side_effect=[{'access_token': 'private'}, profile]) as request:
                updated = refresh_profile(account, account_store=self.accounts, secret_store=self.secrets, now=self.now)
                refresh_profile(updated, account_store=self.accounts, secret_store=self.secrets, now=self.now + timedelta(hours=1))
            self.assertEqual(updated.picture_url, '')
            self.assertEqual(updated.subject, account.subject)
            self.assertEqual(request.call_count, 2)

    def test_concurrent_disconnect_cannot_be_overwritten_by_photo_hydration(self):
        account = self.account()
        def request(url, **kwargs):
            if 'token' in url:
                return {'access_token': 'private'}
            latest = self.accounts.get_account(account.account_id)
            self.accounts.save_account(replace(latest, status='disconnected'))
            return {'sub': account.subject, 'picture': PICTURE}
        with patch('core.connected_accounts.google.json_request', side_effect=request):
            refresh_profile(account, account_store=self.accounts, secret_store=self.secrets, now=self.now)
        latest = self.accounts.get_account(account.account_id)
        self.assertEqual(latest.status, 'disconnected')
        self.assertEqual(latest.picture_url, '')

    def test_old_records_load_without_a_schema_migration(self):
        account = self.account()
        self.accounts.collections.accounts.update_one({'account_id': account.account_id},
            {'$unset': {'picture_url': '', 'profile_checked_at': ''}})
        old = self.accounts.get_account(account.account_id)
        self.assertEqual(old.picture_url, '')
        self.assertIsNone(old.profile_checked_at)
