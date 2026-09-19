"""Single official External Apps CLI command."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from external_apps.surfaces import run

if __name__ == "__main__":
    run("cli")
