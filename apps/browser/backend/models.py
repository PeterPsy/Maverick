"""Browser app constants and surface metadata."""

from __future__ import annotations


APP_ID = "browser"
STATE_SCHEMA_VERSION = "1"
STATE_FILE = "state.json"

READ_ONLY_ACTIONS = frozenset(
    {
        "session.create",
        "session.close",
        "navigate",
        "snapshot",
        "screenshot",
        "console.messages",
        "network.requests",
        "tabs",
        "wait_for",
    }
)
DEV_INSPECTOR_ACTIONS = frozenset({"click", "type", "press_key"})
AUDITED_ACTIONS = READ_ONLY_ACTIONS | DEV_INSPECTOR_ACTIONS

MCP_TOOL_ACTIONS = {
    "browser_session_create": "session.create",
    "browser_session_close": "session.close",
    "browser_navigate": "navigate",
    "browser_snapshot": "snapshot",
    "browser_take_screenshot": "screenshot",
    "browser_console_messages": "console.messages",
    "browser_network_requests": "network.requests",
    "browser_tabs": "tabs",
    "browser_wait_for": "wait_for",
    "browser_click": "click",
    "browser_type": "type",
    "browser_press_key": "press_key",
}
