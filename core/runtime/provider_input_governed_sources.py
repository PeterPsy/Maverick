"""Exact source decomposition for governed inter-agent provider context."""

from __future__ import annotations


def generalist_context_source_chunks(
    content: object,
) -> tuple[tuple[str, object], ...] | None:
    """Return the closed, stable source set represented by one context payload."""
    if not isinstance(content, dict):
        return None
    required = {
        "run_id",
        "status",
        "summary",
        "progress",
        "quality_gate",
        "tasks",
        "artifacts",
    }
    if set(content) != required:
        return None
    run_id = content.get("run_id")
    tasks = content.get("tasks")
    artifacts = content.get("artifacts")
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or not isinstance(tasks, list)
        or not isinstance(artifacts, list)
        or any(not isinstance(item, dict) for item in (*tasks, *artifacts))
    ):
        return None
    base_ref = f"inter-agent-run:{run_id}"
    chunks: list[tuple[str, object]] = [
        (
            f"{base_ref}:control",
            {
                "run_id": run_id,
                "status": content["status"],
                "progress": content["progress"],
                "quality_gate": content["quality_gate"],
                "task_count": len(tasks),
                "artifact_count": len(artifacts),
            },
        ),
        (f"{base_ref}:summary", {"summary": content["summary"]}),
    ]
    seen_task_ids: set[str] = set()
    for item in tasks:
        task_id = item.get("task_id")
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or task_id in seen_task_ids
        ):
            return None
        seen_task_ids.add(task_id)
        chunks.append((f"{base_ref}:task:{task_id}", item))
    chunks.extend(
        (f"{base_ref}:artifact:{index}", item)
        for index, item in enumerate(artifacts)
    )
    return tuple(chunks)


__all__ = ["generalist_context_source_chunks"]
