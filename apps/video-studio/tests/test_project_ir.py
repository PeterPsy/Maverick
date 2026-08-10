"""Project IR v1 schema, canonicalization, validation, and security tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from project_ir import IRValidationError, ProjectIR, ValidationLimits  # noqa: E402
from project_ir.canonical import CanonicalizationError, canonical_dumps, content_digest  # noqa: E402


FIXTURE_PATH = APP_ROOT / "tests" / "fixtures" / "project-ir-v1-golden.json"
SCHEMA_PATH = APP_ROOT / "schemas" / "project-ir.v1.schema.json"
GOLDEN_DIGEST = "297ecf3c9091dea85a32c151a090ac58a287b13e63faa0c87fd7cafff64da894"


def golden() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def error_codes(document: object, **kwargs) -> set[str]:
    with unittest.TestCase().assertRaises(IRValidationError) as raised:
        ProjectIR.parse(document, workspace_id="workspace-test", **kwargs)
    return {item.code for item in raised.exception.issues}


class ProjectIRSchemaTest(unittest.TestCase):
    def test_versioned_schema_and_golden_fixture_parse(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        document = golden()

        self.assertEqual(schema["$id"], "urn:maverick:video-studio:project-ir:v1")
        self.assertEqual(schema["properties"]["ir_version"]["const"], "video-project-ir.v1")
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("transition", schema["$defs"])
        self.assertIn("audioClip", schema["$defs"])
        self.assertEqual(ProjectIR.parse(document, workspace_id="workspace-test").to_dict(), document)

    def test_canonical_serialization_and_digest_are_stable(self) -> None:
        document = golden()
        reversed_document = {key: document[key] for key in reversed(document)}
        first = ProjectIR.parse(document, workspace_id="workspace-test")
        second = ProjectIR.parse(reversed_document, workspace_id="workspace-test")

        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(first.digest, GOLDEN_DIGEST)
        self.assertEqual(content_digest(json.loads(first.canonical_json())), GOLDEN_DIGEST)
        self.assertNotIn(": ", first.canonical_json())
        self.assertLess(first.canonical_json().index('"assets"'), first.canonical_json().index('"audio"'))

    def test_empty_project_is_valid_and_renderer_independent(self) -> None:
        project = ProjectIR.empty(
            project_id="project-empty",
            workspace_id="workspace-test",
            name="Empty",
            frame_rate_numerator=30000,
            frame_rate_denominator=1001,
        )
        serialized = project.canonical_json()

        self.assertEqual(project.document["frame_rate"], {"numerator": 30000, "denominator": 1001})
        for forbidden in ("remotion", "ffmpeg", "javascript", "python"):
            self.assertNotIn(forbidden, serialized.lower())

    def test_canonical_profile_rejects_float_and_non_json_values(self) -> None:
        with self.assertRaisesRegex(CanonicalizationError, "Floating-point"):
            canonical_dumps({"opacity": 0.5})
        with self.assertRaises(CanonicalizationError):
            canonical_dumps({"value": object()})


class ProjectIRNegativeValidationTest(unittest.TestCase):
    def test_security_profile_rejects_active_content_remote_and_host_references(self) -> None:
        cases = (
            ("script", "return process.env", "active_content_field_forbidden"),
            ("source_url", "https://example.invalid/media.mp4", "remote_reference_forbidden"),
            ("local_path", "/home/operator/media.mp4", "host_path_forbidden"),
            ("markup", "<script>alert(1)</script>", "active_markup_forbidden"),
            ("credential", "secret-value", "active_content_field_forbidden"),
            ("shell_command", "ffmpeg -i x", "active_content_field_forbidden"),
        )
        for key, value, expected in cases:
            with self.subTest(key=key):
                document = golden()
                document["metadata"][key] = value
                self.assertIn(expected, error_codes(document))

    def test_ids_references_ranges_and_track_types_are_checked(self) -> None:
        mutations = []

        duplicate = golden()
        duplicate["timeline"]["tracks"][0]["clips"][0]["clip_id"] = "asset-video"
        mutations.append((duplicate, "id_duplicate"))

        missing_asset = golden()
        missing_asset["timeline"]["tracks"][0]["clips"][0]["asset_id"] = "asset-missing"
        mutations.append((missing_asset, "asset_reference_missing"))

        source_range = golden()
        source_range["timeline"]["tracks"][0]["clips"][0]["source"]["out_pts"] = 999999
        mutations.append((source_range, "source_range_exceeds_asset"))

        clip_outside = golden()
        clip_outside["timeline"]["tracks"][0]["clips"][1]["duration_frames"] = 121
        mutations.append((clip_outside, "clip_outside_project"))

        wrong_track = golden()
        wrong_track["timeline"]["tracks"][1]["clips"][0]["kind"] = "video"
        mutations.append((wrong_track, "track_clip_incompatible"))

        overlap = golden()
        overlap["timeline"]["tracks"][0]["clips"][1]["start_frame"] = 119
        mutations.append((overlap, "clip_overlap"))

        external = golden()
        external["assets"][0]["provenance"]["workspace_id"] = "other-workspace"
        mutations.append((external, "external_asset_reference"))

        for document, expected in mutations:
            with self.subTest(expected=expected):
                self.assertIn(expected, error_codes(document))

    def test_transition_keyframe_effect_font_and_template_registries_are_checked(self) -> None:
        transition = golden()
        transition["timeline"]["transitions"][0]["duration_frames"] = 121
        self.assertIn("transition_duration_invalid", error_codes(transition))

        keyframes = golden()
        keyframes["timeline"]["tracks"][0]["clips"][0]["keyframes"][1]["frame"] = 0
        self.assertIn("keyframes_not_ordered", error_codes(keyframes))

        effect = golden()
        effect["timeline"]["tracks"][0]["clips"][0]["effects"][0]["parameters"] = {
            "amount_permille": 5000
        }
        self.assertIn("effect_parameter_range", error_codes(effect))

        font = golden()
        font["timeline"]["tracks"][2]["clips"][0]["text"]["font"] = {
            "id": "host-font",
            "version": "1",
        }
        self.assertIn("font_not_registered", error_codes(font))

        template = golden()
        template["timeline"]["template_instances"][0]["registry"]["id"] = "template.unknown"
        self.assertIn("template_not_registered", error_codes(template))

    def test_vfr_rational_audio_envelope_and_group_cycles_are_checked(self) -> None:
        vfr = golden()
        vfr["assets"][0]["source"]["pts_map"] = [0, 100, 99]
        self.assertIn("vfr_pts_not_monotonic", error_codes(vfr))

        rational = golden()
        rational["frame_rate"] = {"numerator": 48000, "denominator": 2002}
        self.assertIn("rational_not_normalized", error_codes(rational))

        envelope = golden()
        points = envelope["timeline"]["tracks"][1]["clips"][0]["audio"]["envelope"]
        points[1]["frame"] = 0
        self.assertIn("audio_envelope_invalid", error_codes(envelope))

        cycle = golden()
        cycle["timeline"]["groups"].extend(
            [
                {"group_id": "group-one", "name": "One", "member_ids": ["group-two"]},
                {"group_id": "group-two", "name": "Two", "member_ids": ["group-one"]},
            ]
        )
        self.assertIn("group_cycle", error_codes(cycle))

    def test_complexity_limits_are_configurable(self) -> None:
        limits = ValidationLimits(max_tracks=2)
        self.assertIn("complexity_limit_exceeded", error_codes(golden(), limits=limits))

        tiny_document = ValidationLimits(max_document_bytes=100)
        self.assertIn("document_limit_exceeded", error_codes(golden(), limits=tiny_document))

    def test_errors_have_stable_code_path_message_and_deterministic_details(self) -> None:
        document = golden()
        document["timeline"]["tracks"][0]["clips"][0]["asset_id"] = "missing"
        payloads = []
        for _ in range(2):
            try:
                ProjectIR.parse(deepcopy(document), workspace_id="workspace-test")
            except IRValidationError as error:
                payloads.append(error.to_dict())
        self.assertEqual(payloads[0], payloads[1])
        first = payloads[0]["details"]["issues"][0]
        self.assertEqual(set(first), {"code", "path", "message", "details"})
        self.assertEqual(payloads[0]["code"], "project_ir_invalid")


if __name__ == "__main__":
    unittest.main()
