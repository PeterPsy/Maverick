"""Browser video derivatives retain originals and follow source changes."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from errors import StorageValidationError
from drive_localization import stream_url_for_localization
from service import handle_action
from video_preview import browser_video_response


class VideoPreviewTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.source = self.root / 'source.mp4'
        self.source.write_bytes(b'original HEVC bytes')
        self.response = {'path': str(self.source), 'content_type': 'video/mp4',
                         'file_name': 'exercise.mp4', 'etag': 'source-v1', 'download': False}

    def render(self):
        return browser_video_response(data_root=self.root / 'data', file_response=self.response)

    def test_hevc_is_converted_once_without_replacing_original_and_changes_invalidate_cache(self):
        def convert(source, target):
            target.write_bytes(b'H264 playback bytes')
        with patch('video_preview._native_browser_video', return_value=False), patch(
                'video_preview._convert_video', side_effect=convert) as converter:
            first = self.render()
            second = self.render()
            self.assertEqual(first, second)
            self.assertEqual(converter.call_count, 1)
            self.assertNotEqual(first['path'], str(self.source))
            self.assertEqual(Path(first['path']).read_bytes(), b'H264 playback bytes')
            self.assertEqual(self.source.read_bytes(), b'original HEVC bytes')
            self.assertNotEqual(first['etag'], self.response['etag'])
            self.source.write_bytes(b'updated source')
            self.assertNotEqual(self.render()['path'], first['path'])
            self.assertEqual(converter.call_count, 2)

    def test_native_video_and_original_downloads_are_not_transcoded(self):
        with patch('video_preview._native_browser_video', return_value=True), patch('video_preview._convert_video') as converter:
            self.assertEqual(self.render(), self.response)
            self.response['download'] = True
            self.assertEqual(self.render(), self.response)
            converter.assert_not_called()

    def test_failure_or_source_change_never_publishes_partial_derivatives(self):
        def fail(source, target):
            target.write_bytes(b'partial')
            raise StorageValidationError('Conversion failed')
        def change(source, target):
            target.write_bytes(b'complete')
            source.write_bytes(b'different source')
        for conversion in (fail, change):
            with patch('video_preview._native_browser_video', return_value=False), patch(
                    'video_preview._convert_video', side_effect=conversion), self.assertRaises(StorageValidationError):
                self.render()
            self.assertFalse(list((self.root / 'data' / 'video_previews').glob('*.mp4')))

    def test_media_route_serves_derivative_but_download_keeps_the_original(self):
        def convert(source, target):
            target.write_bytes(b'H264 preview')
        body = {'action': 'file.media_stream', 'role': 'generated', 'relative_path': 'source.mp4', 'preview': 'browser'}
        with patch('video_preview._native_browser_video', return_value=False), patch('video_preview._convert_video', side_effect=convert):
            status, media = handle_action(self.root / 'data', self.root / 'uploads', self.root, body, media_route=True)
            self.assertEqual(status, 200)
            self.assertEqual(Path(media['file_response']['path']).read_bytes(), b'H264 preview')
            _, download = handle_action(self.root / 'data', self.root / 'uploads', self.root,
                                       {**body, 'download': True}, media_route=True)
            self.assertEqual(Path(download['file_response']['path']), self.source)
            self.assertEqual(self.source.read_bytes(), b'original HEVC bytes')

    def test_drive_localization_urls_select_browser_playback_only_for_video_previews(self):
        record = {'file_id': 'file_drive', 'preview_kind': 'video', 'source_version': 'v1'}
        stream = stream_url_for_localization(app_id='storage', file_record=record, localization_id='local')
        download = stream_url_for_localization(app_id='storage', file_record=record, localization_id='local', download=True)
        self.assertIn('preview=browser', stream)
        self.assertNotIn('preview=browser', download)


if __name__ == '__main__':
    unittest.main()
