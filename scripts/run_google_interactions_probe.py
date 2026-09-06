#!/usr/bin/env python3
"""Operator-only synthetic live probe used by the Google certification manifest."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.certification_target import builtin_api_certification_target
from core.providers.certification_probe_budget import CertificationProbeTransport
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.google_interactions_transport import GoogleInteractionsHttpTransport
from core.providers.google_interactions_probe import probe_google_interactions


async def _main() -> int:
    value = os.environ.get("MAVERICK_GOOGLE_CERTIFICATION_API_KEY", "").strip()
    if not value:
        return 2
    result = await probe_google_interactions(
        credential=EphemeralCredential(value),
        client=GoogleInteractionsAgenticClient(state_mode="stateless", transport=CertificationProbeTransport(
            GoogleInteractionsHttpTransport(), provider_id="google-ai-studio",
        )),
        request_interval_seconds=_request_interval_seconds(),
    )
    print(json.dumps({
        **result.__dict__,
        "target_digest": builtin_api_certification_target("google-ai-studio"),
        "run_nonce": os.environ.get("MAVERICK_CERTIFICATION_RUN_NONCE", ""),
    }, sort_keys=True))
    return 0 if result.succeeded else 1


def _request_interval_seconds() -> float:
    try:
        value = float(os.environ.get("MAVERICK_CERTIFICATION_PROBE_INTERVAL_SECONDS", "1"))
    except ValueError:
        return 1.0
    return max(0.0, min(value, 30.0))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
