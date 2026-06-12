from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
MAVERICK_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(MAVERICK_ROOT))
sys.path.insert(0, str(APP_ROOT / "backend"))

from service import FitnessCoachError, app_events_for_action, handle_action, validate_workout  # noqa: E402


MEDIA_REF = {
    "kind": "local_file",
    "provider": "local",
    "file_id": "file_test_media",
    "workspace_relative_path": "storage/uploaded/test/video.png",
    "display_path": "storage/uploaded/test/video.png",
    "name": "video.png",
    "content_type": "image/png",
    "preview_kind": "image",
    "size_bytes": 1200,
    "sha256": "abc",
    "etag_or_version": "abc",
    "capabilities": {"can_read": True, "can_preview": True},
}


class FitnessCoachServiceTest(unittest.TestCase):
    def test_workout_crud_validate_start_and_runs(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            status, exercise_payload = handle_action(
                data_root,
                "exercise.create",
                {
                    "title": "Squat",
                    "short_description": "Drive through feet.",
                    "long_description": "Keep chest tall and knees tracking.",
                    "tags": ["legs", "warmup"],
                    "primary_media": MEDIA_REF,
                },
            )
            self.assertEqual(status, 201)
            exercise = exercise_payload["exercise"]

            block = {
                "id": "block_1",
                "type": "work",
                "exercise_id": exercise["id"],
                "exercise_snapshot_updated_at": exercise["updated_at"],
                "title": exercise["title"],
                "short_description": exercise["short_description"],
                "long_description": exercise["long_description"],
                "tags": exercise["tags"],
                "mode": "timer",
                "seconds": 30,
                "reps": None,
                "reps_label": None,
                "media": exercise["primary_media"],
                "notes": None,
            }
            status, workout_payload = handle_action(data_root, "workout.create", {"name": "Morning", "blocks": [block]})
            self.assertEqual(status, 201)
            workout = workout_payload["workout"]
            validation = validate_workout(workout)
            self.assertTrue(validation["valid"])
            self.assertEqual(validation["estimated_seconds"], 45)
            self.assertEqual(len(workout["blocks"]), 1)

            status, validation_payload = handle_action(data_root, "workout.validate", {"workout_id": workout["id"]})
            self.assertEqual(status, 200)
            self.assertTrue(validation_payload["validation"]["valid"])
            self.assertEqual(validation_payload["validation"]["estimated_seconds"], 45)

            status, start_payload = handle_action(data_root, "workout.start", {"workout_id": workout["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(start_payload["workout"]["last_started_at"], start_payload["started_at"])

            status, run_payload = handle_action(
                data_root,
                "workout.complete",
                {"workout_id": workout["id"], "elapsed_seconds": 31, "completed_segments": 1, "skipped_segments": 0},
            )
            self.assertEqual(status, 201)
            self.assertEqual(run_payload["run"]["workout_id"], workout["id"])

            status, runs_payload = handle_action(data_root, "runs.list", {"workout_id": workout["id"]})
            self.assertEqual(status, 200)
            self.assertEqual(len(runs_payload["runs"]), 1)

    def test_duplicate_and_delete_workout(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            _, created = handle_action(data_root, "workout.create", {"name": "Base"})
            workout_id = created["workout"]["id"]
            status, duplicated = handle_action(data_root, "workout.duplicate", {"workout_id": workout_id})
            self.assertEqual(status, 201)
            self.assertNotEqual(duplicated["workout"]["id"], workout_id)
            status, deleted = handle_action(data_root, "workout.delete", {"workout_id": workout_id})
            self.assertEqual(status, 200)
            self.assertEqual(deleted["deleted_id"], workout_id)

    def test_bootstrap_returns_initial_view_in_one_payload(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            _, exercise_payload = handle_action(
                data_root,
                "exercise.create",
                {
                    "title": "Squat",
                    "short_description": "Drive through feet.",
                    "long_description": "Keep chest tall and knees tracking.",
                    "tags": ["legs", "warmup"],
                    "primary_media": MEDIA_REF,
                },
            )
            exercise = exercise_payload["exercise"]
            block = {
                "type": "work",
                "exercise_id": exercise["id"],
                "title": exercise["title"],
                "short_description": exercise["short_description"],
                "long_description": exercise["long_description"],
                "tags": exercise["tags"],
                "mode": "timer",
                "seconds": 30,
                "media": exercise["primary_media"],
            }
            _, workout_payload = handle_action(data_root, "workout.create", {"name": "Morning", "blocks": [block]})

            status, payload = handle_action(data_root, "app.bootstrap", {"include_runs": True, "_workspace_id": "default", "_app_id": "fitness-coach"})

            self.assertEqual(status, 200)
            self.assertEqual(payload["workspace_id"], "default")
            self.assertEqual(payload["app_id"], "fitness-coach")
            self.assertTrue(payload["state_version"])
            self.assertEqual(payload["selected_workout"]["id"], workout_payload["workout"]["id"])
            self.assertEqual(payload["workout_summaries"][0]["work_block_count"], 1)
            self.assertEqual(payload["workout_summaries"][0]["estimated_seconds"], 45)
            self.assertEqual(payload["tags"], ["legs", "warmup"])
            self.assertEqual(payload["runs"], [])
            self.assertEqual(payload["view_state"]["selected_workout_id"], workout_payload["workout"]["id"])

    def test_start_accepts_workout_update_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            _, exercise_payload = handle_action(data_root, "exercise.create", {"title": "Squat", "long_description": "Move well.", "primary_media": MEDIA_REF})
            exercise = exercise_payload["exercise"]
            _, workout_payload = handle_action(data_root, "workout.create", {"name": "Draft"})
            workout = workout_payload["workout"]
            workout["blocks"] = [
                {
                    "type": "work",
                    "exercise_id": exercise["id"],
                    "title": exercise["title"],
                    "short_description": exercise["short_description"],
                    "long_description": exercise["long_description"],
                    "tags": exercise["tags"],
                    "mode": "timer",
                    "seconds": 30,
                    "media": exercise["primary_media"],
                }
            ]

            status, payload = handle_action(data_root, "workout.start", {"workout": workout})

            self.assertEqual(status, 200)
            self.assertEqual(payload["workout"]["id"], workout["id"])
            self.assertEqual(len(payload["workout"]["blocks"]), 1)
            self.assertTrue(payload["validation"]["valid"])
            self.assertEqual(payload["validation"]["estimated_seconds"], 45)
            self.assertEqual(payload["workout"]["last_started_at"], payload["started_at"])

    def test_operations_manifest_exposes_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            status, payload = handle_action(data_root, "operations.manifest", {})

            self.assertEqual(status, 200)
            self.assertIn("app.bootstrap", {item["action"] for item in payload["operations"]})

    def test_exercise_description_derives_legacy_summary(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            description = "Set the feet under the hips, hinge softly, then press through the floor while keeping the ribs stacked."
            status, payload = handle_action(
                data_root,
                "exercise.create",
                {
                    "title": "Hinge press",
                    "long_description": description,
                    "tags": ["posterior-chain"],
                    "primary_media": MEDIA_REF,
                },
            )
            self.assertEqual(status, 201)
            exercise = payload["exercise"]
            self.assertEqual(exercise["long_description"], description)
            self.assertEqual(exercise["short_description"], description)

    def test_media_refs_reject_stream_urls_and_raw_drive_urls(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            bad_media = {**MEDIA_REF, "stream_url": "/api/apps/storage/media?file_id=file_test_media"}
            with self.assertRaises(FitnessCoachError):
                handle_action(data_root, "exercise.create", {"title": "Bad", "primary_media": bad_media})
            bad_drive = {**MEDIA_REF, "display_path": "https://drive.google.com/file/d/raw"}
            with self.assertRaises(FitnessCoachError):
                handle_action(data_root, "exercise.create", {"title": "Bad", "primary_media": bad_drive})

    def test_write_actions_emit_data_changed_events(self) -> None:
        self.assertEqual(app_events_for_action("workout.create")[0]["resource"], "workouts")
        self.assertEqual(app_events_for_action("exercise.update")[0]["resource"], "exercises")
        self.assertEqual(app_events_for_action("workout.complete")[0]["resource"], "runs")
        self.assertEqual(app_events_for_action("view_state.update")[0]["resource"], "view-state")
        self.assertEqual(app_events_for_action("workout.validate"), [])


if __name__ == "__main__":
    unittest.main()
