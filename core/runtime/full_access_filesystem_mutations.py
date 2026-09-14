"""Direct mutation operations for the full-access filesystem facade."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

from core.runtime.confined_filesystem import ConfinedFilesystemResult
from core.runtime.full_access_filesystem_support import require_expected
from core.runtime.tool_errors import RuntimeToolError


class FullAccessFilesystemMutationMixin:
    """Implement host writes without sandbox instruction or COW policy."""

    def write_text(
        self,
        value,
        *,
        content,
        create_only,
        create_parents=True,
        replace_only=False,
        expected_resource_identity=None,
        expected_resource_revision=None,
        mutation_guard=None,
    ):
        if not isinstance(content, str) or (create_only and replace_only):
            raise RuntimeToolError("tool_arguments_invalid")
        path = self.path(value)
        existed = path.exists()
        if create_only and existed:
            raise RuntimeToolError("filesystem_path_exists")
        if replace_only and not existed:
            raise RuntimeToolError("filesystem_path_not_found")
        previous = self._observation(path, "filesystem_file") if existed else None
        require_expected(
            previous,
            expected_resource_identity,
            expected_resource_revision,
        )
        if create_parents:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.parent.is_dir():
            raise RuntimeToolError("filesystem_path_not_found")
        if mutation_guard is not None:
            mutation_guard.verify_before()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".maverick-write-",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if existed:
                shutil.copymode(path, temporary, follow_symlinks=True)
            os.replace(temporary, path)
            temporary = None
            if mutation_guard is not None:
                mutation_guard.verify_after()
        except RuntimeToolError:
            raise
        except OSError as error:
            raise RuntimeToolError("filesystem_write_failed") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        observation = self._observation(path, "filesystem_file")
        payload = {
            "path": str(path),
            "byte_count": len(content.encode("utf-8")),
            "created": not existed,
            "replaced": existed,
            "previous_resource_revision": (
                None if previous is None else previous.resource_revision
            ),
            "previous_resource_digest": (
                None if previous is None else previous.resource_digest
            ),
            "resource_identity": observation.resource_identity,
            "resource_revision": observation.resource_revision,
            "resource_digest": observation.resource_digest,
        }
        return ConfinedFilesystemResult(payload, self._classification(observation))

    def move_path(
        self,
        source_value,
        destination_value,
        *,
        expected_resource_identity=None,
        expected_resource_revision=None,
        create_parents=False,
        mutation_guard=None,
    ):
        source = self.path(source_value)
        destination = self.path(destination_value)
        if not source.exists() and not source.is_symlink():
            raise RuntimeToolError("filesystem_path_not_found")
        if destination.exists() or destination.is_symlink():
            raise RuntimeToolError("filesystem_path_exists")
        before = self._observation(source, "filesystem_path")
        require_expected(
            before,
            expected_resource_identity,
            expected_resource_revision,
        )
        if create_parents:
            destination.parent.mkdir(parents=True, exist_ok=True)
        if mutation_guard is not None:
            mutation_guard.verify_before()
        try:
            shutil.move(source, destination)
        except OSError as error:
            raise RuntimeToolError("filesystem_move_failed") from error
        if mutation_guard is not None:
            mutation_guard.verify_after()
        after = self._observation(destination, "filesystem_path")
        payload = {
            "source_path": str(source),
            "destination_path": str(destination),
            "resource_identity": after.resource_identity,
            "resource_revision": after.resource_revision,
            "resource_digest": after.resource_digest,
        }
        return ConfinedFilesystemResult(payload, self._classification(after))

    def delete_path(
        self,
        value,
        *,
        expected_resource_identity=None,
        expected_resource_revision=None,
        recursive=False,
        mutation_guard=None,
    ):
        path = self.path(value)
        if not path.exists() and not path.is_symlink():
            raise RuntimeToolError("filesystem_path_not_found")
        before = self._observation(path, "filesystem_path")
        require_expected(
            before,
            expected_resource_identity,
            expected_resource_revision,
        )
        if mutation_guard is not None:
            mutation_guard.verify_before()
        try:
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path) if recursive else path.rmdir()
            else:
                path.unlink()
        except OSError as error:
            raise RuntimeToolError("filesystem_delete_failed") from error
        if mutation_guard is not None:
            mutation_guard.verify_after()
        payload = {
            "path": str(path),
            "deleted": True,
            "recursive": recursive,
            "resource_identity": before.resource_identity,
            "resource_revision": before.resource_revision,
            "resource_digest": before.resource_digest,
        }
        return ConfinedFilesystemResult(payload, self._classification(before))


__all__ = ["FullAccessFilesystemMutationMixin"]
