"""Bounded DAG validation and timezone-aware recurrence calculations."""

from datetime import UTC, datetime, timedelta
from math import isfinite
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def text(value, name, limit, *, optional=False):
    if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
        raise ValueError(f"{name} must be {'0' if optional else '1'}–{limit} characters")
    return value.strip()


def validate_graph(graph):
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        raise ValueError("Graph requires nodes and edges arrays")
    if not 1 <= len(graph["nodes"]) <= 64 or len(graph["edges"]) > 256:
        raise ValueError("Use 1–64 blocks and at most 256 connections")
    nodes, ids = [], set()
    for node in graph["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not ID.fullmatch(node["id"]) or node["id"].startswith("__") or node["id"] in ids:
            raise ValueError("Block ids must be unique letters, numbers, underscores or hyphens")
        ids.add(node["id"])
        position = node.get("position", {"x": 80, "y": len(nodes) * 180})
        if not isinstance(position, dict) or any(not isinstance(position.get(k), (float, int)) or isinstance(position[k], bool)
            or not isfinite(position[k]) or abs(position[k]) > 100000 for k in ("x", "y")):
            raise ValueError("Invalid block position")
        skills = node.get("skill_ids", [])
        if not isinstance(skills, list) or len(skills) > 8 or any(not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", s) for s in skills):
            raise ValueError("Use at most 8 stable workspace skill ids per block")
        nodes.append({"id": node["id"], "title": text(node.get("title"), "Block title", 120),
                      "instructions": text(node.get("instructions"), "Block instructions", 8000),
                      "skill_ids": list(dict.fromkeys(skills)), "position": {k: position[k] for k in ("x", "y")}})
    edges, pairs, edge_ids = [], set(), set()
    incoming = {key: 0 for key in ids}
    outgoing = {key: [] for key in ids}
    for edge in graph["edges"]:
        if not isinstance(edge, dict):
            raise ValueError("Invalid connection")
        source, target = edge.get("source"), edge.get("target")
        edge_id = edge.get("id", f"{source}-{target}")
        if source not in ids or target not in ids or source == target or (source, target) in pairs or not ID.fullmatch(str(edge_id)) or edge_id in edge_ids:
            raise ValueError("Connections must link distinct existing blocks without duplicates")
        edges.append({"id": edge_id, "source": source, "target": target})
        pairs.add((source, target))
        edge_ids.add(edge_id)
        incoming[target] += 1
        outgoing[source].append(target)
    ready, visited = [key for key, count in incoming.items() if count == 0], 0
    while ready:
        key = ready.pop()
        visited += 1
        for target in outgoing[key]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(ids):
        raise ValueError("Connections cannot form a cycle. The schedule repeats the whole graph.")
    return {"nodes": nodes, "edges": edges}


def validate_schedule(value):
    if not isinstance(value, dict) or value.get("frequency") not in {"manual", "once", "daily", "weekdays", "weekly"}:
        raise ValueError("Choose manual, once, daily, weekdays or weekly")
    zone = text(value.get("timezone", "UTC"), "Timezone", 120)
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("Choose a valid IANA timezone") from error
    time = value.get("time", "09:00")
    if not isinstance(time, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time):
        raise ValueError("Time must use HH:MM")
    weekday = value.get("weekday", 0)
    if not isinstance(weekday, int) or isinstance(weekday, bool) or not 0 <= weekday <= 6:
        raise ValueError("Weekday must be 0 (Monday) through 6 (Sunday)")
    date = value.get("date", "")
    if value["frequency"] == "once":
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except (TypeError, ValueError) as error:
            raise ValueError("A one-time schedule requires a date (YYYY-MM-DD)") from error
    return {"frequency": value["frequency"], "timezone": zone, "time": time, "weekday": weekday, "date": date if value["frequency"] == "once" else ""}


def next_due(schedule, after):
    frequency = schedule["frequency"]
    if frequency == "manual":
        return None
    zone = ZoneInfo(schedule["timezone"])
    local = datetime.fromtimestamp(after, UTC).astimezone(zone)
    hour, minute = map(int, schedule["time"].split(":"))
    first = datetime.strptime(schedule["date"], "%Y-%m-%d").date() if frequency == "once" else local.date()
    for offset in range(9 if frequency != "once" else 1):
        day = first + timedelta(days=offset)
        if frequency == "weekdays" and day.weekday() >= 5 or frequency == "weekly" and day.weekday() != schedule["weekday"]:
            continue
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
        # A spring-forward gap runs at the normalized local time; an autumn fold runs once.
        timestamp = candidate.timestamp()
        if timestamp > after:
            return timestamp
    return None


def validate_config(body, previous=None):
    value = {**(previous or {}), **body}
    profile = text(value.get("workspace_profile_binding_id", ""), "Model selection", 160, optional=True)
    effort = value.get("reasoning_effort", "")
    if effort not in {"", "low", "medium", "high", "xhigh", "max", "ultra"}:
        raise ValueError("Invalid reasoning effort")
    mode = value.get("conversation_mode", "new")
    if mode not in {"new", "reuse"}:
        raise ValueError("Conversation mode must be new or reuse")
    return {"title": text(value.get("title"), "Title", 160),
            "instructions": text(value.get("instructions", ""), "Instructions", 8000, optional=True),
            "graph": validate_graph(value.get("graph")),
            "schedule": validate_schedule(value.get("schedule", {"frequency": "manual", "timezone": "UTC"})),
            "workspace_profile_binding_id": profile, "reasoning_effort": effort,
            "project_id": text(value.get("project_id", ""), "Project", 160, optional=True),
            "conversation_mode": mode, "notifications": value.get("notifications", True) is True}
