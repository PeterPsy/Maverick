"""Operator entrypoint for the default workspace's dedicated provider service."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from provider_service import ProviderServiceError, operate

if __name__ == "__main__":
    try:
        print(json.dumps(operate(sys.argv[1] if len(sys.argv) > 1 else "status")))
    except ProviderServiceError as error:
        raise SystemExit(str(error)) from None
