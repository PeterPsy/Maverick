"""Bounded External Apps MCP runner; same service and action validation as CLI."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from external_apps.surfaces import run

if __name__ == "__main__":
    run("mcp")
