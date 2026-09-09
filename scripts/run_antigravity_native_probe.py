#!/usr/bin/env python3
"""Run one budgeted, structured Antigravity connection smoke observation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.providers.agentic_adapter import (
    RuntimeCloseContext,
    RuntimePrepareContext,
    RuntimeTurnContext,
)
from core.providers.antigravity_cli_native import AntigravityCliNativeAdapter
from core.providers.certification_budget_ledger import CertificationBudgetLedger
from core.providers.certification_target import native_connection_target_digest
from core.providers.errors import CapabilityCertificateError
from core.providers.native_agent_builtins import (
    build_antigravity_cli_candidate_definition,
    build_antigravity_cli_candidate_installation,
)
from core.providers.native_agent_discovery import (
    discover_antigravity_native_catalog,
)
from core.providers.native_runtime_artifact import (
    ANTIGRAVITY_CLI_RUNTIME_ARTIFACT,
    inspect_native_runtime_artifact,
)
from core.providers.provider_registry import ProviderRegistry
from core.runtime.execution_binding import canonical_digest


async def _probe() -> dict[str, object]:
    environment = os.environ
    if environment.get("MAVERICK_CERTIFICATION_ALLOW_LIVE") != "1":
        raise CapabilityCertificateError("certification_live_opt_in_required")
    nonce = str(environment.get("MAVERICK_CERTIFICATION_RUN_NONCE") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise CapabilityCertificateError("certification_live_receipt_invalid")
    try:
        maximum = int(environment["MAVERICK_CERTIFICATION_MAX_COST_MICROUSD"])
        reservation = int(
            environment.get(
                "MAVERICK_CERTIFICATION_ANTIGRAVITY_RESERVATION_MICROUSD",
                "100000",
            )
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CapabilityCertificateError(
            "certification_live_budget_invalid"
        ) from error
    if not 0 < reservation <= maximum <= 100_000_000:
        raise CapabilityCertificateError("certification_live_budget_invalid")
    ledger = CertificationBudgetLedger(
        Path(environment["MAVERICK_CERTIFICATION_BUDGET_LEDGER"]),
        policy_digest=environment[
            "MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST"
        ],
    )
    command = str(environment.get("MAVERICK_ANTIGRAVITY_COMMAND") or "agy")
    observed_artifact = inspect_native_runtime_artifact(command)
    if observed_artifact != ANTIGRAVITY_CLI_RUNTIME_ARTIFACT:
        raise CapabilityCertificateError("native_runtime_artifact_mismatch")
    adapter = AntigravityCliNativeAdapter(command=command)
    installation = build_antigravity_cli_candidate_installation(command=command)
    model_id = str(
        environment.get("MAVERICK_ANTIGRAVITY_CERTIFICATION_MODEL")
        or "gemini-3.6-flash-high"
    ).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", model_id):
        raise CapabilityCertificateError("native_agent_model_unavailable")
    target_digest = native_connection_target_digest(
        installation,
        model_provider_id="google",
    )
    reservation_args = {
        "provider_id": "google-ai-studio",
        "cost_microusd": reservation,
        "payload_digest": canonical_digest(
            {
                "scope": "native_connection",
                "target_digest": target_digest,
                "model_id": model_id,
                "run_nonce": nonce,
                "max_output_tokens": 16_384,
            }
        ),
        "run_id": f"antigravity:{nonce}",
    }
    while delay := ledger.reserve(**reservation_args):
        await asyncio.sleep(delay)
    try:
        snapshot = discover_antigravity_native_catalog(adapter, force=True)
    except BaseException:
        ledger.halt("google-ai-studio", reason="provider_transport_error")
        raise
    if (
        snapshot is None
        or not snapshot.models
        or model_id not in {model.model_id for model in snapshot.models}
    ):
        ledger.halt("google-ai-studio", reason="provider_response_invalid")
        raise CapabilityCertificateError("native_agent_model_unavailable")

    registry = ProviderRegistry()
    registry.register_native_agent_installation(
        installation,
        definition=build_antigravity_cli_candidate_definition(),
        engine_adapter=adapter,
    )
    controller = registry.get_native_agent_controller("antigravity-cli")
    marker = f"MAVERICK_ANTIGRAVITY_SMOKE_{nonce[:16]}"
    with tempfile.TemporaryDirectory(
        prefix="maverick-antigravity-certification-"
    ) as folder:
        root = Path(folder)
        workspace = root / "workspace"
        runtime = root / "runtime"
        workspace.mkdir()
        runtime.mkdir()
        session = SimpleNamespace(
            session_id=f"antigravity-certification-{nonce}",
            workspace_id=f"certification-antigravity-{nonce}",
            workspace_root=str(workspace),
            workdir=str(workspace),
            runtime_root=str(runtime),
            effective_mode="sandbox",
        )
        binding = SimpleNamespace(
            model_id=model_id,
            model_provider_id="google",
            credential_binding_id=None,
            model_revision_policy="provider_alias",
            reasoning_effort=None,
            execution_family="native_agent",
        )
        state = SimpleNamespace(provider_thread_id=None)
        prepare_context = RuntimePrepareContext(
            session=session,
            binding=binding,
            provider_state=state,
        )
        close_context = RuntimeCloseContext(
            session=session,
            binding=binding,
            provider_state=state,
        )
        try:
            prepared = await controller.prepare(prepare_context)
            events = [
                event
                async for event in controller.execute(
                    RuntimeTurnContext(
                        session=session,
                        binding=binding,
                        provider_state=state,
                        input_text=(
                            f"Reply with exactly {marker} and nothing else. "
                            "Do not call any tool."
                        ),
                        correlation_id=f"probe-{nonce}",
                        timeout_seconds=300,
                    )
                )
            ]
        except BaseException:
            ledger.halt("google-ai-studio", reason="provider_transport_error")
            raise
        finally:
            closed = await controller.close(close_context)
        finals = [
            str(event.payload.get("text") or "")
            for event in events
            if event.event_type == "runtime.output.final"
        ]
        if len(finals) != 1 or finals[0].strip() != marker:
            ledger.halt("google-ai-studio", reason="provider_response_invalid")
            raise CapabilityCertificateError(
                "certification_live_response_invalid"
            )
        provider_thread = str(
            prepared.provider_state_updates.get("provider_thread_id") or ""
        )
        return {
            "target_digest": target_digest,
            "run_nonce": nonce,
            "succeeded": True,
            "request_count": 1,
            "reasoning_efforts": ["default"],
            "saw_init": prepared.ready and bool(provider_thread),
            "saw_structured_event": any(
                event.event_type.startswith("runtime.") for event in events
            ),
            "saw_usage": any(
                event.event_type == "provider.usage" for event in events
            ),
            "saw_nonempty_final": bool(finals[0].strip()),
            "cleanup_verified": bool(closed.closed and not adapter._owners),
            "runtime_artifact_digest": observed_artifact.digest,
            "catalog_snapshot_digest": snapshot.digest,
            "catalog_model_count": len(snapshot.models),
            "provider_thread_digest": hashlib.sha256(
                provider_thread.encode()
            ).hexdigest(),
            "output_digest": hashlib.sha256(finals[0].encode()).hexdigest(),
        }


def main() -> int:
    print(json.dumps(asyncio.run(_probe()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
