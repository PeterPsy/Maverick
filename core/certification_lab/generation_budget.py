"""Bind the actual hosted transports to a job ledger and fresh lab authority."""

from contextlib import aclosing
from dataclasses import dataclass
import hmac

from core.certification_lab.errors import LabAuthorizationError
from core.providers.certification_job_budget import CertificationGenerationLimits, CertificationJobTransport


@dataclass(frozen=True)
class LabGenerationAuthorization:
    state: object
    lab: object

    def revalidate(self, credential):
        from core.runtime.hosted_agentic_transport import revalidate_hosted_generation

        # This is the actual prepared-request guard from the shared loop. It
        # refreshes mutable TCB, policy, actor, attestation and credential after
        # pacing too, not merely the permit or the initially captured snapshot.
        fresh = revalidate_hosted_generation()
        self.lab.validate_session(fresh.context.session)
        if credential is None or fresh.credential is None or not hmac.compare_digest(
            credential.reveal().encode(), fresh.credential.reveal().encode(),
        ):
            raise LabAuthorizationError('lab_credential_changed')

    def wrap(self, transport, *, config, recipe):
        return LabBudgetedTransport(transport, authorization=self, config=config, recipe=recipe)


class LabBudgetedTransport:
    """No generation path, including finalization/recovery, can omit the ledger."""

    def __init__(self, transport, *, authorization, config, recipe):
        self.transport = transport
        self.endpoint = transport.endpoint
        self.authorization = authorization
        self.config = config
        self.recipe = recipe

    async def stream(self, *, payload, credential):
        lab = self.authorization.lab
        session = lab.runtime_store.get_session(lab.ownership.session_id)
        permit = lab.validate_session(session)
        if (self.config.model_provider_id != permit.target.model_provider_id
                or self.endpoint != permit.target.endpoint_url
                or self.config.token_cost_policy.digest != permit.budget.pricing_digest
                or self.config.digest != session.execution_binding.provider_config_digest):
            raise LabAuthorizationError('lab_generation_target_mismatch')
        # The natural Google loop uses stateless history. A remote retained-state
        # reference without a persistent token ceiling is never silently billed.
        if payload.get('previous_interaction_id'):
            raise LabAuthorizationError('lab_stateful_generation_not_granted')
        lab.evidence.record('provider_generation_payload', payload)
        fence = CertificationJobTransport(
            self.transport, ledger=lab.ledger, run_id=permit.job_id,
            pricing=self.config.token_cost_policy, authorization=self.authorization,
            limits=CertificationGenerationLimits(
                self.config.model_provider_id, self.recipe.model_id, self.endpoint,
                permit.policy_ceiling.max_input_tokens, permit.policy_ceiling.max_output_tokens,
                permit.budget.pricing_digest,
            ),
        )
        async with aclosing(fence.stream(payload=payload, credential=credential)) as events:
            async for event in events:
                yield event
