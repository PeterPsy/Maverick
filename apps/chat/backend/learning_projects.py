"""Chat-owned organization for learning agent conversations."""

from pathlib import Path

from chat_state import create_project, mutate_state, read_state, state_path

NAMES = {"memory": "Memory", "improvement": "Improvements"}


def learning_projects(data_root, *, ensure=False):
    path = state_path(Path(data_root))
    changed = False
    current = read_state(path)
    if ensure and set(NAMES).issubset({project.get("learning_kind") for project in current["projects"]}):
        return {project["learning_kind"]: project["project_id"] for project in current["projects"] if project.get("learning_kind") in NAMES}, False

    def organize(state):
        nonlocal changed
        for kind, name in NAMES.items():
            project = next((project for project in state["projects"] if project.get("learning_kind") == kind), None)
            if project is None:
                project = next((project for project in state["projects"] if project.get("name") == name and not project.get("learning_kind")), None)
                if project is None:
                    identifier = create_project(state, {"name": name})["project_id"]
                    project = next(project for project in state["projects"] if project["project_id"] == identifier)
                project["learning_kind"] = kind
                changed = True
        return {}

    if ensure:
        state, _ = mutate_state(path, organize)
    else:
        state = read_state(path)
    return {project["learning_kind"]: project["project_id"] for project in state["projects"]
            if project.get("learning_kind") in NAMES}, changed
