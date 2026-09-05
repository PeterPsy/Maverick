"""Reject declarative guarantees that have no executable implementation."""

from dataclasses import replace
import unittest

from core.providers.errors import AgenticProfileError
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.maverick_agent_onboarding import (
    MaverickAgentOnboardingCatalog,
    MaverickProtocolRuntimeRegistration,
)
from core.runtime.hosted_runtime_registry_builder import _google_interactions_runtime
from tests.support.maverick_agent_onboarding import google_publication


def catalog(publication, factory=_google_interactions_runtime):
    result = MaverickAgentOnboardingCatalog()
    result.register_protocol_adapter(MaverickProtocolRuntimeRegistration(publication.adapter, factory))
    result.register_provider_config(publication.provider_config)
    result.register_profile(publication)
    return result


class MaverickRuntimeNegativeContractTest(unittest.TestCase):
    def test_each_declared_implementation_must_match_the_factory(self):
        base = google_publication()
        for field in (
            "transport_id", "request_codec_id", "response_codec_id",
            "private_state_codec_id", "usage_accounting_id", "cancellation_id", "recovery_id",
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                AgenticProfileError, "implementation_mismatch"
            ):
                catalog(replace(base, adapter=replace(base.adapter, **{field: "wrong"}))).build_runtime_registry()

    def test_client_must_implement_the_request_contract(self):
        def factory(config, recipe):
            runtime = _google_interactions_runtime(config, recipe)
            runtime.client.create_response = None
            return runtime

        with self.assertRaisesRegex(AgenticProfileError, "client_incomplete"):
            catalog(google_publication(), factory).build_runtime_registry()

    def test_usage_method_is_not_a_request_estimator(self):
        def factory(config, recipe):
            return replace(
                _google_interactions_runtime(config, recipe),
                cost_estimator=config.token_cost_policy.usage_cost_microusd,
            )

        with self.assertRaisesRegex(AgenticProfileError, "accounting_identity_mismatch"):
            catalog(google_publication(), factory).build_runtime_registry()

    def test_recovery_requires_executable_components(self):
        for field in ("private_state_inspector", "context_compactor", "request_preflight"):
            def factory(config, recipe):
                return replace(_google_interactions_runtime(config, recipe), **{field: None})

            with self.subTest(field=field), self.assertRaisesRegex(AgenticProfileError, "recovery_incomplete"):
                catalog(google_publication(), factory).build_runtime_registry()

    def test_google_rejects_unattested_retention_guarantees(self):
        routing = google_publication().provider_config.routing_constraint
        for patch in (
            {"data_collection_policy": "deny"},
            {"require_zdr": True},
            {"data_collection_policy": "deny", "require_zdr": True},
        ):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, "unsupported"):
                GoogleInteractionsAgenticClient(routing_constraint=replace(routing, **patch))


if __name__ == "__main__":
    unittest.main()
