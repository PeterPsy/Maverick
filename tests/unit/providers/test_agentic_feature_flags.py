"""Normative agentic rollout flag and kill-switch tests."""

from __future__ import annotations

from dataclasses import replace
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.agentic_models import codex_runtime_policy
from core.providers.errors import CapabilityCertificateError
from core.runtime.authority import intersect_runtime_policies
from core.runtime.agentic_feature_flags import (
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
    MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_PARALLEL_TOOL_CALLS,
    MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
    feature_enabled,
    parallel_tool_calls_enabled,
    provider_preview_feature,
    require_agentic_feature,
)
from core.runtime.hosted_agentic_models import HostedAgenticLoopError
from core.runtime.hosted_provider_runtime import HostedProviderRuntimeRegistry


_NORMATIVE_FLAGS = (
    MAVERICK_FEATURE_AGENTIC_PROFILES,
    MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
    MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
    MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
    MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
    MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
    MAVERICK_FEATURE_PARALLEL_TOOL_CALLS,
)


class AgenticFeatureFlagsTest(unittest.TestCase):
    def test_local_surfaces_default_on_and_remote_agentic_defaults_off(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            for name in (
                MAVERICK_FEATURE_AGENTIC_PROFILES,
                MAVERICK_FEATURE_AGENTIC_ADAPTER_CONTRACT,
                MAVERICK_FEATURE_AGENTIC_TOOL_CONFIRMATION,
                MAVERICK_FEATURE_PROVIDER_PRIVATE_STATE,
                MAVERICK_FEATURE_AGENTIC_EGRESS_ENFORCEMENT,
            ):
                with self.subTest(name=name):
                    self.assertTrue(feature_enabled(name))
            for name in (
                MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
                MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW,
                MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW,
            ):
                with self.subTest(name=name):
                    self.assertFalse(feature_enabled(name))
            self.assertFalse(parallel_tool_calls_enabled())

    def test_every_flag_is_independently_disabled(self) -> None:
        for disabled in _NORMATIVE_FLAGS:
            environment = {name: "1" for name in _NORMATIVE_FLAGS}
            environment[disabled] = "off"
            with self.subTest(disabled=disabled):
                self.assertFalse(feature_enabled(disabled, environment=environment))
                self.assertTrue(
                    all(
                        feature_enabled(name, environment=environment)
                        for name in _NORMATIVE_FLAGS
                        if name != disabled
                    )
                )

    def test_invalid_value_fails_closed_regardless_of_declared_default(self) -> None:
        environment = {MAVERICK_FEATURE_AGENTIC_PROFILES: "invalid"}
        self.assertFalse(
            feature_enabled(MAVERICK_FEATURE_AGENTIC_PROFILES, environment=environment)
        )
        self.assertFalse(
            feature_enabled(
                MAVERICK_FEATURE_AGENTIC_PROFILES,
                default=False,
                environment=environment,
            )
        )

    def test_runtime_guard_returns_stable_blocked_reason(self) -> None:
        with patch.dict(
            os.environ,
            {MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: "0"},
            clear=False,
        ):
            with self.assertRaises(HostedAgenticLoopError) as raised:
                require_agentic_feature(
                    MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME,
                    "hosted_agent_runtime_disabled",
                )
        self.assertEqual(raised.exception.reason_code, "hosted_agent_runtime_disabled")

    def test_provider_preview_flags_are_provider_specific(self) -> None:
        self.assertEqual(
            provider_preview_feature("google-ai-studio"),
            (MAVERICK_FEATURE_GOOGLE_AGENTIC_PREVIEW, "google_agentic_preview_disabled"),
        )
        self.assertEqual(
            provider_preview_feature("openrouter"),
            (MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW, "openrouter_agentic_preview_disabled"),
        )
        self.assertIsNone(provider_preview_feature("codex"))

    def test_provider_kill_switch_is_enforced_during_live_resolution(self) -> None:
        binding = SimpleNamespace(
            model_provider_id="openrouter",
            provider_protocol="openrouter-chat-completions",
            provider_api_version="v1",
        )
        with patch.dict(
            os.environ,
            {
                MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME: "1",
                MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW: "0",
            },
            clear=False,
        ):
            with self.assertRaises(HostedAgenticLoopError) as raised:
                HostedProviderRuntimeRegistry().resolve(binding)
        self.assertEqual(raised.exception.reason_code, "openrouter_agentic_preview_disabled")

    def test_parallel_policy_requires_its_independent_flag(self) -> None:
        policy = replace(codex_runtime_policy(), max_parallel_tool_calls=2)
        with patch.dict(
            os.environ,
            {MAVERICK_FEATURE_PARALLEL_TOOL_CALLS: "0"},
            clear=False,
        ):
            with self.assertRaises(CapabilityCertificateError) as raised:
                intersect_runtime_policies(policy)
        self.assertEqual(raised.exception.reason_code, "parallel_tool_calls_disabled")

        with patch.dict(
            os.environ,
            {MAVERICK_FEATURE_PARALLEL_TOOL_CALLS: "1"},
            clear=False,
        ):
            self.assertEqual(intersect_runtime_policies(policy).max_parallel_tool_calls, 2)


if __name__ == "__main__":
    unittest.main()
