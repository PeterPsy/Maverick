"""Reusable durable pre-generation fence, independent of probe round limits."""

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.certification_budget_ledger import CertificationBudgetLedger
from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest


class CertificationGenerationAuthorization(Protocol):
    """Trusted composition rechecks permit/actor/credential after every wait."""

    def revalidate(self, credential: EphemeralCredential) -> None: ...


@dataclass(frozen=True)
class CertificationGenerationLimits:
    provider_id: str
    model_id: str
    endpoint: str
    max_input_tokens: int
    max_output_tokens: int
    pricing_digest: str


class CertificationJobTransport:
    """Fence *each* actual HTTP generation, across phases, turns and processes.

    This wrapper supplies no authorization itself. Both the protocol probe and
    the natural worker must supply their respective trusted authorization base.
    There is no fallback to a transport without a ledger or to paid Google.
    """

    def __init__(self, transport, *, ledger: CertificationBudgetLedger, run_id: str,
                 limits: CertificationGenerationLimits, pricing, authorization: CertificationGenerationAuthorization):
        if not isinstance(ledger, CertificationBudgetLedger):
            raise CapabilityCertificateError("certification_budget_ledger_required")
        if authorization is None or not callable(getattr(authorization, 'revalidate', None)):
            raise CapabilityCertificateError("certification_generation_authority_required")
        self.transport = transport
        self.endpoint = transport.endpoint
        self.ledger = ledger
        self.run_id = run_id
        self.limits = limits
        self.pricing = pricing
        self.authorization = authorization
        self._validate_configuration()

    def _validate_configuration(self):
        limits = self.limits
        if (self.endpoint != limits.endpoint or self.transport.endpoint != limits.endpoint
                or limits.provider_id not in {"google-ai-studio", "openrouter"}
                or canonical_digest(self.pricing) != limits.pricing_digest
                or type(limits.max_input_tokens) is not int or limits.max_input_tokens < 1
                or type(limits.max_output_tokens) is not int or limits.max_output_tokens < 1):
            raise CapabilityCertificateError("certification_generation_configuration_mismatch")
        # Loading status also verifies the current private ledger and policy.
        status = self.ledger.status().get(limits.provider_id)
        if status is None:
            raise CapabilityCertificateError("certification_budget_provider_unapproved")
        if (limits.provider_id == "google-ai-studio"
                and (status['billing_mode'] != 'free_tier' or status['max_cost_microusd'] != 0)):
            raise CapabilityCertificateError("certification_budget_policy_invalid")

    async def stream(self, *, payload, credential, retained_input_ceiling=0):
        self._validate_configuration()
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        # Detach caller-owned containers before pacing. A different payload must
        # never consume a reservation made for earlier, cheaper bytes.
        payload = json.loads(encoded)
        input_ceiling = len(encoded) + 64 + retained_input_ceiling
        output_ceiling = payload.get('max_tokens', payload.get('generation_config', {}).get('max_output_tokens'))
        if (type(output_ceiling) is not int or not 0 < output_ceiling <= self.limits.max_output_tokens
                or type(retained_input_ceiling) is not int or retained_input_ceiling < 0
                or input_ceiling > self.limits.max_input_tokens or payload.get('model') != self.limits.model_id
                or (payload.get('previous_interaction_id') and retained_input_ceiling == 0)):
            raise CapabilityCertificateError("certification_generation_request_limit")
        cost = self.pricing.usage_cost_microusd(input_ceiling, output_ceiling)
        while True:
            self.authorization.revalidate(credential)
            self._validate_configuration()
            delay = self.ledger.reserve(
                provider_id=self.limits.provider_id, cost_microusd=cost,
                payload_digest=hashlib.sha256(encoded).hexdigest(), run_id=self.run_id,
            )
            if not delay:
                break
            await asyncio.sleep(delay)
        # Fresh authority and credential AFTER the reservation/pacing and before
        # HTTPS. Cancellation or failed revalidation never refunds the reserve.
        self.authorization.revalidate(credential)
        try:
            async with aclosing(self.transport.stream(payload=payload, credential=credential)) as events:
                async for event in events:
                    self.authorization.revalidate(credential)
                    if provider_stream_failure(event):
                        self.ledger.halt(self.limits.provider_id, reason="provider_stream_error")
                    yield event
        except Exception:
            # Cancellation/GeneratorExit retain the reservation; session/WAL
            # ownership, not a budget refund, governs ambiguous recovery.
            self.ledger.halt(self.limits.provider_id, reason="provider_transport_error")
            raise


def provider_stream_failure(event):
    if event.get("error") or event.get("event_type", event.get("type")) == "error":
        return True
    interaction = event.get("interaction")
    if isinstance(interaction, dict) and interaction.get("status") in {"failed", "incomplete", "budget_exceeded"}:
        return True
    choices = event.get("choices")
    return isinstance(choices, list) and any(
        isinstance(choice, dict) and choice.get("finish_reason") == "error" for choice in choices
    )
