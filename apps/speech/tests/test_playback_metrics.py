from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = APP_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from errors import SpeechValidationError
from playback_metrics import record_playback_metrics_payload
from store import read_jobs


class PlaybackMetricsTestCase(unittest.TestCase):
    def test_playback_updates_preserve_initial_latency_metrics(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            record_playback_metrics_payload(
                data_root,
                {
                    "playback_id": "browser-test-123",
                    "mode": "pcm-stream",
                    "outcome": "playing",
                    "generation_id": "gen_test_123",
                    "tap_to_request_ms": 4.25,
                    "browser_first_chunk_ms": 181.5,
                    "tap_to_audio_playing_ms": 246.75,
                    "underrun_count": 0,
                    "audio_context_state": "running",
                    "audio_session_type": "playback",
                },
            )
            record_playback_metrics_payload(
                data_root,
                {
                    "playback_id": "browser-test-123",
                    "mode": "pcm-stream",
                    "outcome": "completed",
                    "underrun_count": 1,
                },
            )
            jobs = read_jobs(data_root)["jobs"]

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["kind"], "tts_playback")
        self.assertEqual(jobs[0]["outcome"], "completed")
        self.assertEqual(jobs[0]["generation_id"], "gen_test_123")
        self.assertEqual(jobs[0]["tap_to_audio_playing_ms"], 246.75)
        self.assertEqual(jobs[0]["underrun_count"], 1)
        self.assertEqual(jobs[0]["audio_context_state"], "running")
        self.assertEqual(jobs[0]["audio_session_type"], "playback")
        self.assertIn("updated_at", jobs[0])

    def test_playback_metrics_reject_unbounded_client_identifier(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self.assertRaises(SpeechValidationError):
                record_playback_metrics_payload(
                    Path(temp_dir),
                    {
                        "playback_id": "not a safe id",
                        "mode": "buffered",
                    },
                )


if __name__ == "__main__":
    unittest.main()
