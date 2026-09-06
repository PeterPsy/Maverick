"""Operator opt-in and conservative, non-refundable live-probe reservations."""

import json
import os
from contextlib import aclosing
from pathlib import Path

from core.providers.certification_budget_ledger import CertificationBudgetLedger
from core.providers.certification_job_budget import CertificationGenerationLimits, CertificationJobTransport
from core.runtime.execution_binding import canonical_digest
from core.providers.certification_target import builtin_api_certification_profile
from core.providers.errors import CapabilityCertificateError


class CertificationProbeTransport:
    """Check the actual translated payload before delegating to HTTPS transport."""

    def __init__(self, transport, *, provider_id, environment=None):
        from core.providers.maverick_agent_builtins import builtin_maverick_agent_publications

        env = os.environ if environment is None else environment
        self.environment = env
        try:
            maximum = int(env.get("MAVERICK_CERTIFICATION_MAX_COST_MICROUSD", ""))
            if env.get("MAVERICK_CERTIFICATION_ALLOW_LIVE") != "1" or not 0 < maximum <= 100_000_000:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise CapabilityCertificateError("certification_live_opt_in_required") from error
        publication = next(p for p in builtin_maverick_agent_publications()
                           if p.profile.model_provider_id == provider_id)
        self.endpoint = transport.endpoint
        if self.endpoint != publication.provider_config.endpoint_url:
            raise CapabilityCertificateError("certification_target_mismatch")
        self.transport = transport
        try:
            self.ledger = CertificationBudgetLedger(
                Path(env["MAVERICK_CERTIFICATION_BUDGET_LEDGER"]),
                policy_digest=env["MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST"],
            )
            self.run_id = env["MAVERICK_CERTIFICATION_RUN_NONCE"]
        except KeyError as error:
            raise CapabilityCertificateError("certification_budget_ledger_required") from error
        self.provider_id = provider_id
        self.profile = builtin_api_certification_profile(provider_id)
        self.pricing = publication.provider_config.token_cost_policy
        self.maximum = maximum
        self.reserved = 0
        self.requests = 0
        self.retained_context_ceiling = 0
        rounds = 3 if provider_id == "google-ai-studio" else 4
        self.max_requests = rounds * len(publication.recipe.support_flags.reasoning_efforts)
        self.job_transport = CertificationJobTransport(
            transport, ledger=self.ledger, run_id=self.run_id, pricing=self.pricing, authorization=self,
            limits=CertificationGenerationLimits(
                provider_id, self.profile.model_id, self.endpoint,
                self.profile.policy_ceiling.max_input_tokens, self.profile.policy_ceiling.max_output_tokens,
                canonical_digest(self.pricing),
            ),
        )

    def revalidate(self, _credential):
        env = self.environment
        if (env.get("MAVERICK_CERTIFICATION_ALLOW_LIVE") != "1"
                or env.get("MAVERICK_CERTIFICATION_RUN_NONCE") != self.run_id
                or env.get("MAVERICK_CERTIFICATION_BUDGET_LEDGER") != str(self.ledger.path)
                or env.get("MAVERICK_CERTIFICATION_BUDGET_POLICY_DIGEST") != self.ledger.policy_digest
                or str(self.maximum) != str(env.get("MAVERICK_CERTIFICATION_MAX_COST_MICROUSD"))):
            raise CapabilityCertificateError("certification_live_opt_in_required")
        if self.requests > self.max_requests or self.reserved > self.maximum:
            raise CapabilityCertificateError("certification_probe_request_limit")

    async def stream(self, *, payload, credential):
        # One token per serialized byte is deliberately more conservative than
        # the ordinary estimated bytes/token rate, and includes schemas/history.
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        input_ceiling = len(encoded) + 64
        if self.provider_id == "google-ai-studio" and payload.get("previous_interaction_id"):
            # Stateful Interactions can bill retained history which is not in
            # this request's serialized bytes. Include all previously reserved
            # input and output, including ambiguous/failed responses.
            input_ceiling += self.retained_context_ceiling
        output_ceiling = payload.get("max_tokens", payload.get("generation_config", {}).get("max_output_tokens"))
        policy = self.profile.policy_ceiling
        if (type(output_ceiling) is not int or not 0 < output_ceiling <= policy.max_output_tokens
                or input_ceiling > policy.max_input_tokens or payload.get("model") != self.profile.model_id
                or self.requests >= self.max_requests):
            raise CapabilityCertificateError("certification_probe_request_limit")
        reservation = self.pricing.usage_cost_microusd(input_ceiling, output_ceiling)
        if self.reserved + reservation > self.maximum:
            raise CapabilityCertificateError("certification_probe_budget_exceeded")
        retained_input = self.retained_context_ceiling if payload.get("previous_interaction_id") else 0
        self.reserved += reservation
        self.requests += 1
        self.retained_context_ceiling = input_ceiling + output_ceiling
        # Round counts and per-probe limits stay here; the reusable job fence
        # owns durable aggregate reservations and post-pacing revalidation.
        async with aclosing(self.job_transport.stream(
            payload=payload, credential=credential, retained_input_ceiling=retained_input,
        )) as events:
            async for event in events:
                yield event
