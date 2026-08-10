"""Typed Project IR document and configurable complexity limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canonical import canonical_copy, canonical_dumps, content_digest
from .registry import ProjectRegistry, default_registry


@dataclass(frozen=True)
class ValidationLimits:
    max_document_bytes: int = 2_000_000
    max_tracks: int = 128
    max_clips: int = 10_000
    max_layers: int = 20_000
    max_keyframes: int = 100_000
    max_effects: int = 50_000
    max_transitions: int = 20_000
    max_captions: int = 100_000
    max_markers: int = 20_000
    max_groups: int = 10_000
    max_text_characters: int = 500_000

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"Validation limit `{name}` must be a positive integer.")


@dataclass(frozen=True)
class ProjectIR:
    """Validated immutable-by-copy Project IR v1 aggregate."""

    document: dict[str, Any]

    @classmethod
    def parse(
        cls,
        document: object,
        *,
        workspace_id: str | None = None,
        registry: ProjectRegistry | None = None,
        limits: ValidationLimits | None = None,
    ) -> "ProjectIR":
        from .validator import validate_project_ir

        validate_project_ir(
            document,
            workspace_id=workspace_id,
            registry=registry or default_registry(),
            limits=limits or ValidationLimits(),
        )
        assert isinstance(document, dict)
        return cls(canonical_copy(document))

    @classmethod
    def empty(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        name: str,
        width: int = 1920,
        height: int = 1080,
        frame_rate_numerator: int = 30,
        frame_rate_denominator: int = 1,
        sample_rate: int = 48_000,
    ) -> "ProjectIR":
        return cls.parse(
            {
                "ir_version": "video-project-ir.v1",
                "metadata": {
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "name": name,
                    "tags": [],
                    "provenance": [],
                },
                "canvas": {
                    "width": width,
                    "height": height,
                    "pixel_aspect": {"numerator": 1, "denominator": 1},
                    "background": {"kind": "color", "value": "#000000FF"},
                    "color_space": "rec709",
                },
                "frame_rate": {
                    "numerator": frame_rate_numerator,
                    "denominator": frame_rate_denominator,
                },
                "audio": {"sample_rate": sample_rate, "channel_layout": "stereo"},
                "duration_frames": 0,
                "assets": [],
                "timeline": {
                    "tracks": [],
                    "transitions": [],
                    "captions": [],
                    "markers": [],
                    "template_instances": [],
                    "groups": [],
                    "relationships": [],
                },
            },
            workspace_id=workspace_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return canonical_copy(self.document)

    def canonical_json(self) -> str:
        return canonical_dumps(self.document)

    @property
    def digest(self) -> str:
        return content_digest(self.document)
