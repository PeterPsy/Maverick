"""Converted browser previews use authenticated files, stable signatures, and atomic cache publication."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from errors import StorageValidationError
from service import handle_action


class PreviewStreamTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.data = self.root / 'data'
        self.uploaded = self.root / 'storage' / 'uploaded'
        self.generated = self.root / 'storage' / 'generated'
        self.data.mkdir()
        self.uploaded.mkdir(parents=True)
        self.generated.mkdir()
        self.source = self.generated / 'brief.docx'
        self.source.write_bytes(b'fake office source')

    def action(self, **body):
        return handle_action(self.data, self.uploaded, self.generated, body)

    def test_browser_render_uses_authenticated_stream_without_base64_or_file_bytes_in_json(self):
        def convert(source, target):
            target.write_bytes(b'%PDF-1.4\nconverted preview')
        with patch('render_preview._convert_to_pdf', side_effect=convert) as renderer, patch.object(
                Path, 'read_bytes', side_effect=AssertionError('preview JSON must not read a converted blob')):
            status, payload = self.action(action='render_preview', role='generated', relative_path='brief.docx', response_mode='stream')
            self.assertEqual(status, 200)
            self.assertNotIn('content_base64', payload)
            query = {key: values[0] for key, values in parse_qs(urlsplit(payload['stream_url']).query).items()}
            self.assertEqual(urlsplit(payload['stream_url']).path, '/api/apps/storage/media')
            with self.assertRaisesRegex(StorageValidationError, 'authenticated'):
                self.action(action='file.media_stream', **query)
            status, media = handle_action(self.data, self.uploaded, self.generated,
                {'action': 'file.media_stream', **query}, media_route=True)
            self.assertEqual(status, 200)
            self.assertEqual(media['file_response']['content_type'], 'application/pdf')
            self.assertEqual(media['file_response']['cache_control'], 'private, no-store')
            self.assertEqual(renderer.call_count, 1)
        self.assertEqual(Path(media['file_response']['path']).read_bytes(), b'%PDF-1.4\nconverted preview')
        before = self.source.stat()
        self.source.write_bytes(b'changed same bytes')
        os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(StorageValidationError, 'source changed'):
            handle_action(self.data, self.uploaded, self.generated, {'action': 'file.media_stream', **query}, media_route=True)

    def test_conversion_failure_never_publishes_a_partial_derivative(self):
        def partial(source, target):
            target.write_bytes(b'%PDF-partial')
            raise OSError('converter died')
        with patch('render_preview._convert_to_pdf', side_effect=partial), self.assertRaises(OSError):
            self.action(action='render_preview', role='generated', relative_path='brief.docx', response_mode='stream')
        self.assertEqual(list((self.data / 'rendered_previews').glob('*.pdf')), [])

    def test_source_change_during_conversion_is_not_cached(self):
        def changing(source, target):
            target.write_bytes(b'%PDF-complete')
            source.write_bytes(b'another document')
        with patch('render_preview._convert_to_pdf', side_effect=changing), self.assertRaisesRegex(StorageValidationError, 'changed during'):
            self.action(action='render_preview', role='generated', relative_path='brief.docx', response_mode='stream')
        self.assertEqual(list((self.data / 'rendered_previews').glob('*.pdf')), [])
