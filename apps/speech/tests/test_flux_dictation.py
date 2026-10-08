"""Regression coverage using Flux's actual TurnInfo wire payloads."""

from __future__ import annotations

import base64
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import flux_streaming
from service import handle_action
from store import read_jobs, write_settings


def turn_event(kind: str, text: str = "", turn_index: int = 0) -> dict:
    return {"type": "TurnInfo", "event": kind, "turn_index": turn_index, "transcript": text}


class ScriptedFluxClient:
    def __init__(self, batches):
        self.batches = list(batches)
        self.pending = []
        self.audio = []
        self.controls = []
        self.closed = False

    def connect(self):
        pass

    def send_binary(self, data):
        self.audio.append(data)
        self.pending.extend(self.batches.pop(0))

    def send_json(self, message):
        self.controls.append(message)

    def receive_json(self, _timeout):
        return self.pending.pop(0) if self.pending else None

    def close(self):
        self.closed = True


class FluxDictationTests(unittest.TestCase):
    def test_turninfo_finalizes_each_turn_instead_of_overwriting_the_previous_sentence(self):
        client = ScriptedFluxClient([
            [turn_event("StartOfTurn"), turn_event("Update", "Prima"), turn_event("Update", "Prima frase.")],
            [turn_event("EndOfTurn", "Prima frase.")],
            [turn_event("StartOfTurn", turn_index=1), turn_event("Update", "Seconda frase.", 1)],
            [turn_event("EndOfTurn", "Seconda frase.", 1)],
        ])
        session = flux_streaming.DeepgramFluxSession(
            session_id="wire-regression", model="flux-general-multi", api_key="test-key", language="",
            client_factory=lambda *_args, **_kwargs: client,
        )
        results = [session.transcribe_chunk(b"chunk", final=index == 3) for index in range(4)]
        self.assertEqual(results[1]["text"], "Prima frase.")
        self.assertEqual(results[-1]["text"], "Prima frase. Seconda frase.")
        self.assertEqual(results[1]["events"][0], {"type": "EndOfTurn", "text": "Prima frase.", "is_final": True})
        self.assertEqual(results[1]["turn_events"], [{"type": "EndOfTurn", "text": "Prima frase."}])
        self.assertEqual(client.controls, [{"type": "CloseStream"}])
        self.assertTrue(client.closed)

    def test_forty_seconds_of_chunked_dictation_preserves_all_sentences_and_audio(self):
        phrases = ["La prima frase deve restare.", "Anche la seconda frase deve restare.", "Questa è la frase finale."]
        batches = []
        for index in range(27):  # Browser timeslice: 1.5 seconds; total about 40 seconds.
            turn_index = min(index // 9, 2)
            events = [turn_event("Update", phrases[turn_index], turn_index)]
            if index % 9 == 8:
                events.append(turn_event("EndOfTurn", phrases[turn_index], turn_index))
            batches.append(events)
        client = ScriptedFluxClient(batches)
        manager = flux_streaming.DeepgramFluxSessionManager(client_factory=lambda *_args, **_kwargs: client)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            write_settings(root, {"transcription_engine": "deepgram"})
            inserted = []
            sent_audio = []
            with patch.object(flux_streaming, "_FLUX_MANAGER", manager):
                for index in range(27):
                    audio = bytes([index]) * 512
                    sent_audio.append(audio)
                    status, result = handle_action(root, root / "generated", {
                        "action": "transcribe_audio", "dictation": True, "session_id": "forty-second-dictation",
                        "chunk_index": index, "final": index == 26, "content_type": "audio/webm",
                        "audio_base64": base64.b64encode(audio).decode(), "_app_secrets": {"deepgram-api-key": "test-key"},
                    })
                    self.assertEqual(status, 200)
                    if result["chunk_text"]:
                        inserted.append(result["chunk_text"])
            self.assertEqual(inserted, phrases)
            self.assertEqual(result["text"], " ".join(phrases))
            self.assertEqual(result["model"], "flux-general-multi")
            self.assertTrue(result["final"])
            self.assertEqual(client.audio, sent_audio)
            jobs = read_jobs(root)["jobs"]
            self.assertEqual(len(jobs), 27)
            self.assertEqual(sum(job["size_bytes"] for job in jobs), sum(map(len, sent_audio)))
            self.assertEqual(sum(bool(job["chunk_transcript_chars"]) for job in jobs), 3)
            self.assertTrue(all(job["retention"] == "metadata_only" for job in jobs))
