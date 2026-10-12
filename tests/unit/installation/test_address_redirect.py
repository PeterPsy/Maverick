import unittest

from core.installation.address_redirect import document_redirect


class AddressRedirectTests(unittest.TestCase):
    configuration = {'hostname': 'new.example.com', 'managed': True}

    def test_old_saved_app_route_forwards_without_header_injection(self):
        self.assertEqual(document_redirect(self.configuration, path='/app/chat', request_host='old.example.com', query='thread=123'),
                         'https://new.example.com/app/chat?thread=123')
        result = document_redirect(self.configuration, path='/app/chat\r\n', request_host='old.example.com', query='x=\r\nheader')
        self.assertNotIn('\r', result)
        self.assertNotIn('\n', result)

    def test_recovery_api_localhost_and_app_frames_do_not_redirect(self):
        for options in [dict(path='/setup'), dict(path='/api/admin/installation'), dict(method='POST'),
                        dict(request_host='localhost:8014'), dict(app_frame=True), dict(request_host='new.example.com')]:
            args = {'path': '/', 'request_host': 'old.example.com', **options}
            with self.subTest(options=options):
                self.assertIsNone(document_redirect(self.configuration, **args))
