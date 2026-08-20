"""OpenRouter catalog-preflight contract regressions."""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
)
from core.providers.agentic_filesystem_probe import FILESYSTEM_LIST_PROBE_TOOL_NAME
from core.providers.openrouter_agentic_catalog import validate_openrouter_agentic_catalog
from core.providers.openrouter_agentic_models import OpenRouterAgenticProtocolError
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


def _request() -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1",
        request_id="catalog-preflight",
        correlation_id="catalog-preflight",
        model_id="deepseek/deepseek-v4-flash",
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
