"""Atomic version-fenced move operations for the confined filesystem."""

from __future__ import annotations

import os
import stat

from core.runtime.confined_filesystem import (
    ConfinedFilesystemResult,
    ConfinedWorkspaceFilesystem,
)
from core.runtime.confined_filesystem_mutation_support import (
    lstat_entry,
    rename_noreplace,
    require_absent,
    require_supported_type,
    resource_kind,
    revalidate_entry,
    rollback_move,
    same_identity,
)
from core.runtime.tool_errors import RuntimeToolError


def move_confined_path(
    filesystem: ConfinedWorkspaceFilesystem,
    source_path: str,
    destination_path: str,
    *,
    expected_resource_identity: str,
    expected_resource_revision: str,
    create_parents: bool,
    mutation_guard=None,
) -> ConfinedFilesystemResult:
    """Atomically move one exact inode while retaining both parent anchors."""
    if not expected_resource_identity or not expected_resource_revision:
        raise RuntimeToolError("filesystem_expected_version_incomplete")
    source = filesystem._components(source_path, allow_root=False)
    destination = filesystem._components(destination_path, allow_root=False)
    if source == destination:
        raise RuntimeToolError("filesystem_move_same_path")
    source_chain = filesystem._open_chain(source[:-1])
    destination_chain = None
    committed = False
    completed = False
    source_stat: os.stat_result | None = None
    destination_stat: os.stat_result | None = None
    source_observation = None
    source_classification = None
    try:
        source_stat = lstat_entry(source_chain.leaf_fd, source[-1])
        require_supported_type(source_stat)
        if stat.S_ISDIR(source_stat.st_mode) and destination[: len(source)] == source:
            raise RuntimeToolError("filesystem_move_destination_inside_source")
        source_observation = filesystem._observation(
            resource_kind(source_stat),
            filesystem._relative(source),
            source_stat,
        )
        filesystem._require_expected(
            source_observation,
            identity=expected_resource_identity,
            revision=expected_resource_revision,
        )
        source_classification = filesystem._classification(
            source_observation,
            "tool_result",
        )
        destination_chain = filesystem._open_chain(
            destination[:-1],
            create_missing=create_parents,
        )
        try:
            lstat_entry(destination_chain.leaf_fd, destination[-1])
        except RuntimeToolError as error:
            if error.reason_code != "filesystem_path_not_found":
                raise
        else:
            raise RuntimeToolError("filesystem_path_exists")
        filesystem._hook("move_before_commit", source_path)
        if mutation_guard is not None:
            mutation_guard.verify_before()
        revalidate_entry(filesystem, source_chain, source[-1], source_stat)
        if (
            filesystem._classification(source_observation, "tool_result")
            != source_classification
        ):
            raise RuntimeToolError("filesystem_resource_changed")
        filesystem._assert_chain(destination_chain)
        rename_noreplace(
            source_chain.leaf_fd,
            source[-1],
            destination_chain.leaf_fd,
            destination[-1],
        )
        committed = True
        destination_stat = lstat_entry(
            destination_chain.leaf_fd,
            destination[-1],
        )
        if not same_identity(source_stat, destination_stat):
            restored = rollback_move(
                destination_chain.leaf_fd,
                destination[-1],
                source_chain.leaf_fd,
                source[-1],
                expected_identity=destination_stat,
            )
            if restored:
                committed = False
                raise RuntimeToolError("filesystem_resource_changed")
            raise RuntimeToolError("tool_execution_unknown")
        require_absent(source_chain.leaf_fd, source[-1])
        os.fsync(source_chain.leaf_fd)
        if destination_chain.leaf_fd != source_chain.leaf_fd:
            os.fsync(destination_chain.leaf_fd)
        filesystem._hook("move_committed", destination_path)
        filesystem._assert_chain(source_chain)
        filesystem._assert_chain(destination_chain)
        if mutation_guard is not None:
            mutation_guard.verify_after()
        moved_observation = filesystem._observation(
            source_observation.resource_kind,
            filesystem._relative(destination),
            destination_stat,
        )
        classification = filesystem._classification_from_mutation_source(
            moved_observation,
            "tool_result",
            source_classification,
        )
        filesystem._forget_mutation_taint(source_observation)
        filesystem._remember_mutation_taint(
            moved_observation,
            source_classification,
        )
        completed = True
        return ConfinedFilesystemResult(
            {
                "source_path": source_observation.resource_ref,
                "destination_path": moved_observation.resource_ref,
                "resource_identity": moved_observation.resource_identity,
                "resource_revision": moved_observation.resource_revision,
                "resource_digest": moved_observation.resource_digest,
            },
            classification,
        )
    except RuntimeToolError as error:
        if committed and destination_stat is not None:
            restored = rollback_move(
                destination_chain.leaf_fd,
                destination[-1],
                source_chain.leaf_fd,
                source[-1],
                expected_identity=destination_stat,
            )
            if restored:
                committed = False
                os.fsync(source_chain.leaf_fd)
                if destination_chain.leaf_fd != source_chain.leaf_fd:
                    os.fsync(destination_chain.leaf_fd)
            elif error.reason_code != "tool_execution_unknown":
                raise RuntimeToolError("tool_execution_unknown") from error
        raise
    except OSError as error:
        if committed:
            raise RuntimeToolError("tool_execution_unknown") from error
        raise RuntimeToolError("filesystem_move_failed") from error
    finally:
        try:
            if (
                destination_chain is not None
                and not completed
                and not destination_chain.rollback_created_directories()
            ):
                raise RuntimeToolError("tool_execution_unknown")
        finally:
            if destination_chain is not None:
                destination_chain.close()
            source_chain.close()
