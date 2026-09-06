"""Operator opt-in and conservative, non-refundable live-probe reservations."""

import json
import os
from contextlib import aclosing

from core.providers.certification_target import builtin_api_certification_profile
from core.providers.errors import CapabilityCertificateError


class CertificationProbeTransport:
    """Check the actual translated payload before delegating to HTTPS transport."""

    def __init__(self, transport, *, provider_id, environment=None):
        from core.providers.maverick_agent_builtins import builtin_maverick_agent_publications

        env = os.environ if environment is None else environment
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
        self.profile = builtin_api_certification_profile(provider_id)
        self.pricing = publication.provider_config.token_cost_policy
        self.maximum = maximum
        self.reserved = 0
        self.requests = 0
        rounds = 3 if provider_id == "google-ai-studio" else 4
        self.max_requests = rounds * len(publication.recipe.support_flags.reasoning_efforts)

    async def stream(self, *, payload, credential):
        # One token per serialized byte is deliberately more conservative than
        # the ordinary estimated bytes/token rate, and includes schemas/history.
        input_ceiling = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) + 64
        output_ceiling = payload.get("max_tokens", payload.get("generation_config", {}).get("max_output_tokens"))
        policy = self.profile.policy_ceiling
        if (type(output_ceiling) is not int or not 0 < output_ceiling <= policy.max_output_tokens
                or input_ceiling > policy.max_input_tokens or payload.get("model") != self.profile.model_id
                or self.requests >= self.max_requests):
            raise CapabilityCertificateError("certification_probe_request_limit")
        reservation = self.pricing.usage_cost_microusd(input_ceiling, output_ceiling)
        if self.reserved + reservation > self.maximum:
            raise CapabilityCertificateError("certification_probe_budget_exceeded")
        self.reserved += reservation
        self.requests += 1
        # Ambiguous/failed requests retain their full charge; never retry/refund.
        async with aclosing(self.transport.stream(payload=payload, credential=credential)) as events:
            async for event in events:
                yield event
