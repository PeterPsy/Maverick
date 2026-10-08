"""Measured word intervals survive editor-independent subtitle preparation."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import SpeechTranscriptionError, SpeechValidationError
from subtitles import prepare_subtitles
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch
from engines import _run_faster_whisper_with_model, _external_faster_whisper_worker_paths
from service import handle_action
from store import read_jobs
from app_backend import backend_worker_config


class SubtitleTests(unittest.TestCase):
    def words(self, texts):
        return [{"start": i * .2, "end": i * .2 + .15, "text": text} for i, text in enumerate(texts)]

    def test_word_limit_keeps_real_boundaries_and_punctuation(self):
        result = prepare_subtitles({"words": self.words(["Uno", "due", "tre", "quattro", "cinque."]), "max_words": 3})
        self.assertEqual([c["text"] for c in result["captions"]], ["Uno due tre", "quattro cinque."])
        self.assertEqual(result["captions"][0]["end"], .55)
        self.assertIn("00:00:00,600 --> 00:00:00,950", result["srt"])

    def test_pauses_punctuation_characters_and_offset(self):
        words = self.words(["Ciao.", "parolalunga", "qui"])
        words[-1].update(start=2, end=2.2)
        result = prepare_subtitles({"words": words, "max_chars": 5, "time_offset_seconds": 1})
        self.assertEqual(len(result["captions"]), 3)
        self.assertEqual(result["captions"][-1]["start"], 3)
        self.assertEqual(result["overlong_word_count"], 1)

    def test_overlap_clips_caption_end_at_next_measured_start(self):
        words = [{"start": 0, "end": .5, "text": "uno"}, {"start": .4, "end": .8, "text": "due"}]
        result = prepare_subtitles({"words": words, "max_words": 1})
        self.assertEqual(result["captions"][0]["end"], .4)

    def test_rejects_fake_precision_invalid_numbers_and_srt_injection(self):
        cases = [
            {"words": [{"start": 0, "end": 2, "text": "una frase intera lunga"}]},
            {"words": self.words(["ciao"]), "max_words": True},
            {"words": [{"start": float("nan"), "end": 2, "text": "ciao"}]},
            {"words": [{"start": 0, "end": .0001, "text": "ciao"}]},
            {"words": [{"start": 0, "end": 1, "text": "ciao\n\n99"}]},
            {"words": self.words(["ciao"]), "time_offset_seconds": -1},
        ]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(SpeechValidationError):
                prepare_subtitles(body)

    def test_silence_has_no_invented_captions(self):
        self.assertEqual(prepare_subtitles({"words": []})["srt"], "")

    def test_whisper_word_mode_is_per_job_and_preserves_measured_timing(self):
        class Model:
            def transcribe(self, path, **options):
                self.options = options
                word = SimpleNamespace(start=.12, end=.37, word=" Ciao!", probability=.9)
                return iter([SimpleNamespace(start=0, end=1, text="Ciao!", words=[word])]), SimpleNamespace(language="it", duration=1)
        model = Model()
        result = _run_faster_whisper_with_model(model, Path("audio.wav"), config={"word_timestamps": True})
        self.assertTrue(model.options["word_timestamps"])
        self.assertEqual(result["words"], [{"start": .12, "end": .37, "text": "Ciao!", "confidence": .9}])
        result = _run_faster_whisper_with_model(model, Path("audio.wav"), config={})
        self.assertFalse(model.options["word_timestamps"])
        self.assertNotIn("words", result)
        config = {"data_root": "/tmp/speech-test", "model": "small"}
        self.assertEqual(_external_faster_whisper_worker_paths(config), _external_faster_whisper_worker_paths({**config, "word_timestamps": True}))

    def test_subtitle_helper_changes_invalidate_the_backend_worker(self):
        names = {item["name"] for item in backend_worker_config()["files"]}
        self.assertTrue({"subtitles.py", "transcription_policy.py"}.issubset(names))

    def test_file_transcription_prepares_subtitles_without_persisting_text(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            uploaded = root / "storage/uploaded"
            uploaded.mkdir(parents=True)
            (uploaded / "audio.wav").write_bytes(b"RIFF" + b"0" * 512)
            result = {"engine": "faster-whisper", "text": "Ciao a tutti", "duration_seconds": 1,
                      "segments": [{"start": 0, "end": 1, "text": "Ciao a tutti"}],
                      "words": self.words(["Ciao", "a", "tutti"])}
            with patch("transcription.transcribe_audio_file", return_value=result) as transcribe, patch("transcription.probe_audio_duration_seconds", return_value=1):
                status, payload = handle_action(root / "data", root / "storage/generated", {
                    "action": "transcribe_file", "workspace_relative_path": "storage/uploaded/audio.wav", "subtitle_max_words": 2,
                }, uploaded)
            self.assertEqual(status, 200)
            self.assertTrue(transcribe.call_args.kwargs["settings"]["_word_timestamps"])
            self.assertEqual([c["text"] for c in payload["subtitles"]["captions"]], ["Ciao a", "tutti"])
            self.assertNotIn("Ciao", str(read_jobs(root / "data")))

    def test_untimed_word_is_reported_and_cannot_silently_disappear_from_subtitles(self):
        class Model:
            def transcribe(self, path, **options):
                words = [SimpleNamespace(start=0, end=.2, word="Ciao", probability=.9),
                         SimpleNamespace(start=.2, end=.2, word="qui", probability=.8)]
                return iter([SimpleNamespace(start=0, end=.5, text="Ciao qui", words=words)]), SimpleNamespace(duration=.5)
        result = _run_faster_whisper_with_model(Model(), Path("audio.wav"), config={"word_timestamps": True})
        self.assertEqual(result["untimed_word_count"], 1)
        with TemporaryDirectory() as directory:
            root = Path(directory); uploaded = root / "storage/uploaded"; uploaded.mkdir(parents=True)
            (uploaded / "audio.wav").write_bytes(b"RIFF" + b"0" * 512)
            with patch("transcription.transcribe_audio_file", return_value=result), patch("transcription.probe_audio_duration_seconds", return_value=.5):
                status, payload = handle_action(root / "data", root / "storage/generated", {
                    "action": "transcribe_file", "workspace_relative_path": "storage/uploaded/audio.wav", "word_timestamps": True,
                }, uploaded)
                self.assertEqual(status, 200)
                self.assertFalse(payload["word_timing"]["complete"])
                with self.assertRaisesRegex(SpeechTranscriptionError, "complete word timing"):
                    handle_action(root / "data", root / "storage/generated", {
                        "action": "transcribe_file", "workspace_relative_path": "storage/uploaded/audio.wav", "subtitle_max_words": 2,
                    }, uploaded)
