"""OpenRouter catalog-preflight contract regressions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import Barrier
import unittest
from unittest.mock import patch

from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
    EphemeralCredential,
)
from core.providers.agentic_filesystem_probe import FILESYSTEM_LIST_PROBE_TOOL_NAME
from core.providers.openrouter_agentic_catalog import (
    OPENROUTER_AGENTIC_ENDPOINT_CATALOG,
    OPENROUTER_ZDR_ENDPOINT_CATALOG,
    preflight_openrouter_agentic_catalog,
    validate_openrouter_agentic_catalog,
)
from core.providers.openrouter_agentic_models import (
    OPENROUTER_AGENTIC_MODEL_REVISION,
    OpenRouterAgenticProtocolError,
)
from core.providers.openrouter_agentic_profile import openrouter_agentic_routing_constraint
from core.providers.openrouter_agentic_request import openrouter_chat_payload
from core.providers.openrouter_agentic_state import decode_openrouter_chat_state


SUPPORTED = [
    "max_tokens",
    "reasoning",
    "reasoning_effort",
    "tool_choice",
    "tools",
]


class OpenRouterAgenticCatalogTest(unittest.TestCase):
    def test_live_catalog_records_are_fetched_within_one_timeout_window(self) -> None:
        rendezvous = Barrier(2)

        def fetch(url, _credential):
            rendezvous.wait(timeout=1)
            return (
                _model_catalog()
                if url == OPENROUTER_AGENTIC_ENDPOINT_CATALOG
                else _zdr_catalog()
            )

        with patch(
            "core.providers.openrouter_agentic_catalog._fetch_catalog",
            side_effect=fetch,
        ) as mocked:
            snapshot = preflight_openrouter_agentic_catalog(
                _request(),
                credential=EphemeralCredential("fixture-openrouter-key"),
            )

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(
            {call.args[0] for call in mocked.call_args_list},
            {
                OPENROUTER_AGENTIC_ENDPOINT_CATALOG,
                OPENROUTER_ZDR_ENDPOINT_CATALOG,
            },
        )
        self.assertEqual(snapshot.upstream_id, "deepinfra/fp8")

    def test_exact_model_and_zdr_records_support_the_request(self) -> None:
        zdr_catalog = _zdr_catalog()
        zdr_catalog["data"][0]["supported_parameters"].append("temperature")
        snapshot = validate_openrouter_agentic_catalog(
            _request(),
            model_catalog=_model_catalog(),
            zdr_catalog=zdr_catalog,
        )

        self.assertEqual(snapshot.upstream_id, "deepinfra/fp8")
        self.assertEqual(snapshot.supported_parameters, tuple(sorted(SUPPORTED)))
        self.assertEqual(len(snapshot.model_catalog_record_digest), 64)
        self.assertEqual(len(snapshot.zdr_catalog_record_digest), 64)
        self.assertTrue(snapshot.supports_tool_choice_none)
        self.assertEqual(snapshot.context_length, 1_048_576)
        self.assertEqual(snapshot.max_completion_tokens, 65_536)
        self.assertEqual(len(snapshot.catalog_snapshot_digest), 64)

    def test_catalog_requires_a_pinned_alias_policy_revision(self) -> None:
        for request in (
            replace(_request(), model_revision=""),
            replace(_request(), model_revision_policy="exact"),
        ):
            with self.subTest(request=request), self.assertRaisesRegex(
                OpenRouterAgenticProtocolError,
                "provider_request_invalid",
            ):
                validate_openrouter_agentic_catalog(
                    request,
                    model_catalog=_model_catalog(),
                    zdr_catalog=_zdr_catalog(),
                )

    def test_catalog_url_rejects_noncanonical_model_path_segments(self) -> None:
        for model_id in (
            "",
            "/vendor/model",
            "vendor//model",
            "vendor/../model",
            "vendor/./model",
        ):
            with self.subTest(model_id=model_id), self.assertRaisesRegex(
                OpenRouterAgenticProtocolError,
                "provider_request_invalid",
            ):
                preflight_openrouter_agentic_catalog(
                    replace(_request(), model_id=model_id),
                    credential=EphemeralCredential("fixture-openrouter-key"),
                )

    def test_every_routed_parameter_must_exist_in_both_catalogs(self) -> None:
        for catalog_name in ("model", "zdr"):
            for parameter in SUPPORTED:
                with self.subTest(catalog=catalog_name, parameter=parameter):
                    model_catalog = _model_catalog()
                    zdr_catalog = _zdr_catalog()
                    target = (
                        model_catalog["data"]["endpoints"][0]
                        if catalog_name == "model"
                        else zdr_catalog["data"][0]
                    )
                    target["supported_parameters"].remove(parameter)

                    with self.assertRaisesRegex(
                        OpenRouterAgenticProtocolError,
                        "provider_endpoint_parameters_unsupported",
                    ):
                        validate_openrouter_agentic_catalog(
                            _request(),
                            model_catalog=model_catalog,
                            zdr_catalog=zdr_catalog,
                        )

    def test_preflight_derives_new_parameters_from_the_translated_payload(self) -> None:
        request = _request()
        payload, messages = openrouter_chat_payload(
            request,
            decode_openrouter_chat_state(request.provider_private_state),
        )
        payload["parallel_tool_calls"] = False

        with patch(
            "core.providers.openrouter_agentic_catalog.openrouter_chat_payload",
            return_value=(payload, messages),
        ), self.assertRaisesRegex(
            OpenRouterAgenticProtocolError,
            "provider_endpoint_parameters_unsupported",
        ):
            validate_openrouter_agentic_catalog(
                request,
                model_catalog=_model_catalog(),
                zdr_catalog=_zdr_catalog(),
            )

    def test_wrong_or_missing_zdr_endpoint_fails_closed(self) -> None:
        for update in (
            {"tag": "another/fp8"},
            {"model_id": "another/model"},
            {"provider_name": "Another"},
            {"quantization": "fp4"},
            {"status": None},
            {"status": False},
            {"status": 1},
            {"max_completion_tokens": 100},
        ):
            with self.subTest(update=update):
                catalog = _zdr_catalog()
                catalog["data"][0].update(update)
                with self.assertRaisesRegex(
                    OpenRouterAgenticProtocolError,
                    "provider_endpoint_parameters_unsupported",
                ):
                    validate_openrouter_agentic_catalog(
                        _request(),
                        model_catalog=_model_catalog(),
                        zdr_catalog=catalog,
                    )

    def test_explicit_none_is_observed_not_required_by_the_tools_omitted_contract(self) -> None:
        model_catalog = _model_catalog()
        zdr_catalog = _zdr_catalog()
        for record in (model_catalog["data"]["endpoints"][0], zdr_catalog["data"][0]):
            record["supports_tool_choice"]["none"] = False
        snapshot = validate_openrouter_agentic_catalog(
            _request(), model_catalog=model_catalog, zdr_catalog=zdr_catalog,
        )
        self.assertFalse(snapshot.supports_tool_choice_none)

    def test_auto_capability_shape_and_total_context_window_are_mandatory(self) -> None:
        for catalog_name in ("model", "zdr"):
            for update in (
                {"supports_tool_choice": {"auto": False, "none": False}},
                {"supports_tool_choice": {"auto": True}},
                {"context_length": 16_384},
            ):
                with self.subTest(catalog=catalog_name, update=update):
                    model_catalog = _model_catalog()
                    zdr_catalog = _zdr_catalog()
                    target = (
                        model_catalog["data"]["endpoints"][0]
                        if catalog_name == "model"
                        else zdr_catalog["data"][0]
                    )
                    target.update(update)
                    with self.assertRaisesRegex(
                        OpenRouterAgenticProtocolError,
                        "provider_endpoint_parameters_unsupported",
                    ):
                        validate_openrouter_agentic_catalog(
                            _request(),
                            model_catalog=model_catalog,
                            zdr_catalog=zdr_catalog,
                        )

    def test_model_upstream_and_quantization_are_request_config_data(self) -> None:
        request = replace(
            _request(),
            model_id="vendor/data-only-model",
            model_revision="catalog-data-only",
            routing_constraint=replace(
                _request().routing_constraint,
                allowed_upstream_ids=("another-provider/fp16",),
                allowed_quantizations=("fp16",),
            ),
        )
        record = {
            **_record(),
            "model_id": "vendor/data-only-model",
            "provider_name": "Another Provider",
            "tag": "another-provider/fp16",
            "quantization": "fp16",
        }
        model_record = dict(record)
        model_record.pop("model_id")

        snapshot = validate_openrouter_agentic_catalog(
            request,
            model_catalog={
                "data": {
                    "id": "vendor/data-only-model",
                    "endpoints": [model_record],
                }
            },
            zdr_catalog={"data": [record]},
            upstream_provider_names=("Another Provider",),
        )

        self.assertEqual(snapshot.upstream_id, "another-provider/fp16")
        payload, _messages = openrouter_chat_payload(
            request,
            decode_openrouter_chat_state(request.provider_private_state),
        )
        self.assertEqual(payload["provider"]["only"], ["another-provider/fp16"])
        self.assertEqual(payload["provider"]["quantizations"], ["fp16"])


def _request() -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1",
        request_id="catalog-preflight",
        correlation_id="catalog-preflight",
        model_id="deepseek/deepseek-v4-flash",
        model_revision=OPENROUTER_AGENTIC_MODEL_REVISION,
        model_revision_policy="provider_alias",
        reasoning_effort="high",
        content_blocks=(
            AgenticRequestContentBlock(
                "catalog-user",
                "user",
                "public",
                "user_input",
                "trusted_platform",
                "text/plain",
                b"synthetic",
            ),
        ),
        tool_definitions=(
            AgenticToolDefinition(
                FILESYSTEM_LIST_PROBE_TOOL_NAME,
                "List synthetic files.",
                {"type": "object"},
            ),
        ),
        tool_results=(),
        provider_private_state=None,
        routing_constraint=openrouter_agentic_routing_constraint(),
        max_output_tokens=16_384,
    )


def _record() -> dict[str, object]:
    return {
        "model_id": "deepseek/deepseek-v4-flash",
        "provider_name": "DeepInfra",
        "tag": "deepinfra/fp8",
        "quantization": "fp8",
        "context_length": 1_048_576,
        "max_completion_tokens": 65_536,
        "supported_parameters": list(SUPPORTED),
        "supports_tool_choice": {"auto": True, "none": True},
        "status": 0,
    }


def _model_catalog() -> dict[str, object]:
    record = deepcopy(_record())
    record.pop("model_id")
    return {
        "data": {
            "id": "deepseek/deepseek-v4-flash",
            "endpoints": [record],
        }
    }


def _zdr_catalog() -> dict[str, object]:
    return {"data": [_record()]}


if __name__ == "__main__":
    unittest.main()
