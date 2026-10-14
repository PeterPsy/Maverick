"""Tests for platform-owned sidecar artifact namespace resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.apps.artifact_mounts import (
    ARTIFACT_NAMESPACE_MARKER,
    create_artifact_namespace,
    platform_artifact_store_root,
    resolve_artifact_mounts,
)
from core.apps.contracts import build_http_sidecar_artifact_mount
from core.apps.errors import AppHostingError


class SidecarArtifactMountTests(unittest.TestCase):
    def test_namespace_is_installation_owned_identity_bound_and_resolved_read_only_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(Path(temp_dir))
            store = root / "data" / "app-artifacts"
            with patch.dict(os.environ, {"LOOPINO_APP_ARTIFACT_STORE_ROOT": str(store)}):
                namespace = create_artifact_namespace(
                    repository_root=root,
                    app_id="design-studio",
                    artifact_id="opendesign",
                )
                mounts = resolve_artifact_mounts(
                    repository_root=root,
                    app_id="design-studio",
                    declarations=[build_http_sidecar_artifact_mount(artifact_id="opendesign")],
                )

            self.assertEqual(mounts[0].source, namespace)
            self.assertEqual(mounts[0].target, Path("/artifacts/opendesign"))
            self.assertIn(root / "data", namespace.parents)
            marker = json.loads((namespace / ARTIFACT_NAMESPACE_MARKER).read_text(encoding="utf-8"))
            self.assertEqual(mounts[0].store_generation, marker["store_generation"])

    def test_repository_store_and_mutable_or_tampered_namespace_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(Path(temp_dir))
            inside = root / "data" / "artifacts"
            with patch.dict(os.environ, {"LOOPINO_APP_ARTIFACT_STORE_ROOT": str(inside)}):
                with self.assertRaisesRegex(AppHostingError, "designated installation"):
                    create_artifact_namespace(
                        repository_root=root,
                        app_id="design-studio",
                        artifact_id="opendesign",
                    )

            store = root / "data" / "app-artifacts"
            with patch.dict(os.environ, {"LOOPINO_APP_ARTIFACT_STORE_ROOT": str(store)}):
                namespace = create_artifact_namespace(
                    repository_root=root,
                    app_id="design-studio",
                    artifact_id="opendesign",
                )
                namespace.chmod(0o770)
                with self.assertRaisesRegex(AppHostingError, "protected"):
                    resolve_artifact_mounts(
                        repository_root=root,
                        app_id="design-studio",
                        declarations=[build_http_sidecar_artifact_mount(artifact_id="opendesign")],
                    )
                namespace.chmod(0o750)
                marker_path = namespace / ARTIFACT_NAMESPACE_MARKER
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                marker["app_id"] = "other-app"
                marker_path.write_text(json.dumps(marker), encoding="utf-8")
                with self.assertRaisesRegex(AppHostingError, "identity"):
                    resolve_artifact_mounts(
                        repository_root=root,
                        app_id="design-studio",
                        declarations=[build_http_sidecar_artifact_mount(artifact_id="opendesign")],
                    )

    def test_default_and_overrides_cannot_escape_installation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(Path(temp_dir))
            with patch.dict(os.environ, {"LOOPINO_APP_ARTIFACT_STORE_ROOT": ""}):
                self.assertEqual(platform_artifact_store_root(root), root / "data/app-artifacts")
            for value in (str(Path(temp_dir) / "external"), "relative", str(root / "apps/artifacts"), str(root / "installation/artifacts"), str(root / "data/control-plane"), str(root / "data")):
                with self.subTest(value=value), patch.dict(os.environ, {"LOOPINO_APP_ARTIFACT_STORE_ROOT": value}):
                    with self.assertRaises(AppHostingError):
                        platform_artifact_store_root(root)
            (root / "data").symlink_to(Path(temp_dir), target_is_directory=True)
            with patch.dict(os.environ, {"LOOPINO_APP_ARTIFACT_STORE_ROOT": ""}):
                with self.assertRaises(AppHostingError):
                    platform_artifact_store_root(root)

    def test_namespace_ids_cannot_traverse_or_select_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self._repository(Path(temp_dir))
            for app_id, artifact_id in (("..", "valid"), ("valid", "../escape"), ("/tmp", "valid")):
                with self.subTest(app_id=app_id, artifact_id=artifact_id), self.assertRaises(AppHostingError):
                    create_artifact_namespace(repository_root=root, app_id=app_id, artifact_id=artifact_id)
            self.assertFalse((root / "data/app-artifacts").exists())

    @staticmethod
    def _repository(parent: Path) -> Path:
        root = parent / "loopino"
        for name in ("apps", "core", "workspaces"):
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / "AGENTS.md").write_text("", encoding="utf-8")
        return root


if __name__ == "__main__":
    unittest.main()
