"""Typed Project IR editing operation tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from projects.batches import OperationBatch  # noqa: E402
from projects.operations import apply_operation_batch  # noqa: E402


FIXTURE = APP_ROOT / "tests" / "fixtures" / "project-ir-v1-golden.json"


def golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def timeline_document() -> dict:
    document = golden()
    document["assets"] = document["assets"][:1]
    document["timeline"] = {
        "tracks": [deepcopy(document["timeline"]["tracks"][0])],
        "transitions": [],
        "captions": [],
        "markers": [],
        "template_instances": [],
        "groups": [],
        "relationships": [],
    }
    for clip in document["timeline"]["tracks"][0]["clips"]:
        clip["keyframes"] = []
        clip["effects"] = []
        clip["layers"] = []
        clip["group_ids"] = []
    return document


def batch(operations: list[dict], *, batch_id: str = "batch-test") -> OperationBatch:
    payload = {
        "workspace_id": "workspace-test",
        "project_id": "project-golden",
        "base_revision_id": "revision-base",
        "operation_batch_id": batch_id,
        "preconditions": [{"type": "entity_exists", "entity_id": "track-video"}],
        "actor": {"kind": "user", "id": "editor-1"},
        "operations": operations,
        "autosave": {"enabled": False, "reason": "test"},
        "metadata": {},
    }
    return OperationBatch.parse(payload, trusted_workspace_id="workspace-test")


def clip(identifier: str, start: int, duration: int, source_in: int, source_out: int) -> dict:
    value = deepcopy(timeline_document()["timeline"]["tracks"][0]["clips"][0])
    value.update(
        {
            "clip_id": identifier,
            "start_frame": start,
            "duration_frames": duration,
            "source": {"in_pts": source_in, "out_pts": source_out},
        }
    )
    return value


class TimelineOperationsTest(unittest.TestCase):
    def test_property_like_timeline_operations_are_valid_and_deterministic(self) -> None:
        cases = {
            "insert": {"type": "timeline.insert", "track_id": "track-video", "clip": clip("clip-new", 120, 20, 1000, 2000)},
            "overwrite": {"type": "timeline.overwrite", "track_id": "track-video", "clip": clip("clip-new", 60, 120, 1000, 2000)},
            "move": {"type": "timeline.move", "clip_id": "clip-video-b", "target_track_id": "track-video", "start_frame": 240},
            "trim": {"type": "timeline.trim", "clip_id": "clip-video-b", "start_frame": 130, "duration_frames": 100, "source_in_pts": 240000, "source_out_pts": 440000},
            "split": {"type": "timeline.split", "clip_id": "clip-video-a", "frame": 60, "right_clip_id": "clip-split"},
            "ripple-delete": {"type": "timeline.ripple_delete", "track_id": "track-video", "start_frame": 60, "duration_frames": 60},
            "ripple-trim": {"type": "timeline.ripple_trim", "clip_id": "clip-video-a", "edge": "end", "delta_frames": 20},
        }
        for name, operation in cases.items():
            with self.subTest(operation=name):
                first, applied = apply_operation_batch(timeline_document(), batch([operation], batch_id=f"batch-{name}"))
                second, _ = apply_operation_batch(timeline_document(), batch([operation], batch_id=f"batch-{name}"))
                self.assertEqual(first, second)
                self.assertEqual(applied, (operation["type"],))

    def test_overwrite_residual_source_ranges_come_from_original_clip(self) -> None:
        operation = {"type": "timeline.overwrite", "track_id": "track-video", "clip": clip("clip-new", 60, 120, 1000, 2000)}
        result, _ = apply_operation_batch(timeline_document(), batch([operation]))
        clips = result["timeline"]["tracks"][0]["clips"]
        right = next(item for item in clips if item["start_frame"] == 180)
        self.assertEqual(right["source"], {"in_pts": 337500, "out_pts": 450000})


class ContentOperationsTest(unittest.TestCase):
    def test_all_non_timeline_typed_operations_share_one_validator(self) -> None:
        document = golden()
        temporary_asset = deepcopy(document["assets"][0])
        temporary_asset["asset_id"] = "asset-temporary"
        operations = [
            {"type": "asset.add", "asset": temporary_asset},
            {"type": "asset.remove", "asset_id": "asset-temporary"},
            {"type": "property.set", "target_type": "clip", "target_id": "clip-video-a", "property": "opacity_permille", "value": 900},
            {"type": "transition.remove", "transition_id": "transition-main"},
            {"type": "transition.add", "transition": document["timeline"]["transitions"][0]},
            {"type": "effect.remove", "clip_id": "clip-video-a", "effect_id": "effect-brightness"},
            {"type": "effect.add", "clip_id": "clip-video-a", "effect": document["timeline"]["tracks"][0]["clips"][0]["effects"][0]},
            {"type": "keyframe.remove", "clip_id": "clip-video-a", "keyframe_id": "keyframe-scale-b"},
            {"type": "keyframe.add", "clip_id": "clip-video-a", "keyframe": {"keyframe_id": "keyframe-new", "property": "transform.scale_x_permille", "frame": 60, "value": 1050, "easing": "linear"}},
            {"type": "keyframe.update", "clip_id": "clip-video-a", "keyframe_id": "keyframe-new", "changes": {"value": 1060}},
            {"type": "caption.add", "caption": {**document["timeline"]["captions"][0], "caption_id": "caption-new", "start_frame": 100}},
            {"type": "caption.update", "caption_id": "caption-new", "changes": {"text": "Updated"}},
            {"type": "caption.remove", "caption_id": "caption-new"},
            {"type": "audio.envelope.add", "clip_id": "clip-audio", "point": {"frame": 100, "gain_millibels": -100, "easing": "linear"}},
            {"type": "audio.envelope.update", "clip_id": "clip-audio", "frame": 100, "point": {"frame": 101, "gain_millibels": -200, "easing": "ease-out"}},
            {"type": "audio.envelope.remove", "clip_id": "clip-audio", "frame": 101},
            {"type": "template.apply", "instance": {"template_instance_id": "template-second", "registry": {"id": "lower-third.basic", "version": "1"}, "start_frame": 150, "duration_frames": 30, "parameters": {"title": "Safe"}}},
            {"type": "group.group", "group": {"group_id": "group-second", "name": "Second", "member_ids": ["clip-video-b"]}},
            {"type": "group.ungroup", "group_id": "group-second"},
            {"type": "project.rename", "name": "Edited project"},
        ]
        result, applied = apply_operation_batch(document, batch(operations, batch_id="batch-content"))
        self.assertEqual(len(applied), len(operations))
        self.assertEqual(result["metadata"]["name"], "Edited project")
        self.assertEqual(result["timeline"]["template_instances"][-1]["template_instance_id"], "template-second")


if __name__ == "__main__":
    unittest.main()
