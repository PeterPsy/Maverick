"""Shared process state for the Codex app-server runtime modules."""

from __future__ import annotations

from dataclasses import dataclass, field
import queue
import subprocess
import threading

from core.runtime.execution_events import RuntimeExecutionEventSink
from core.skills.models import SkillDefinition


@dataclass
class _CodexAppServerRuntime:
    """Live app-server process and request state for one runtime session."""

    session_id: str
    workspace_id: str
    runtime_root: str
    process: subprocess.Popen
    request_lock: threading.Lock = field(default_factory=threading.Lock)
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    steering_lock: threading.Lock = field(default_factory=threading.Lock)
    active_turn_lock: threading.Lock = field(default_factory=threading.Lock)
    event_lock: threading.Lock = field(default_factory=threading.Lock)
    provider_thread_lock: threading.Lock = field(default_factory=threading.Lock)
    generated_system_skills_lock: threading.Lock = field(default_factory=threading.Lock)
    skill_rehydration_lock: threading.Lock = field(default_factory=threading.Lock)
    response_waiters: dict[int, queue.Queue] = field(default_factory=dict)
    next_request_id: int = 1
    provider_thread_id: str | None = None
    current_provider_turn_id: str | None = None
    current_event_sink: RuntimeExecutionEventSink | None = None
    current_chunks: list[str] = field(default_factory=list)
    streamed_agent_item_ids: set[str] = field(default_factory=set)
    pending_agent_json_chunks: dict[str, list[str]] = field(default_factory=dict)
    emitted_structured_keys: set[str] = field(default_factory=set)
    current_error_text: str | None = None
    current_completion_received: bool = False
    completion_queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))
    reader_thread: threading.Thread | None = None
    generated_system_skills_cleaned_home: str | None = None
    current_invoked_skills: tuple[SkillDefinition, ...] = ()
    rehydrated_compaction_items: set[str] = field(default_factory=set)
    skill_rehydration_sequence: int = 0


_RUNTIMES: dict[str, _CodexAppServerRuntime] = {}
_RUNTIMES_LOCK = threading.Lock()
