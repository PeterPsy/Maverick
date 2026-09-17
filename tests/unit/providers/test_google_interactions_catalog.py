from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch
import unittest

from core.providers.agentic_protocol import (
    AgenticModelRequest,
    AgenticRequestContentBlock,
    AgenticToolDefinition,
    EphemeralCredential,
)
from core.providers.google_agentic_profile import google_interactions_routing_constraint
from core.providers.google_interactions_catalog import (
    GOOGLE_INTERACTIONS_MODEL_CATALOG,
    GOOGLE_INTERACTIONS_OPENAPI_CATALOG,
    preflight_google_interactions_catalog,
    validate_google_interactions_catalog,
)
from core.providers.google_interactions_models import GoogleInteractionsProtocolError
from core.runtime.hosted_provider_model_config import GOOGLE_HOSTED_MODEL_CONFIG


class GoogleInteractionsCatalogTest(unittest.TestCase):
    def test_live_preflight_fetches_both_exact_catalogs(self) -> None:
        calls: list[tuple[str, bool]] = []

        def fetch(url, credential):
            calls.append((url, credential is not None))
            return _endpoint_schema() if credential is None else _model_record()

        request = _request(GOOGLE_HOSTED_MODEL_CONFIG, final=False)
        with patch(
            "core.providers.google_interactions_catalog._fetch_catalog",
            side_effect=fetch,
        ):
            snapshot = preflight_google_interactions_catalog(
                request,
                credential=EphemeralCredential("synthetic-key"),
            )

        self.assertCountEqual(
            calls,
            [
                (GOOGLE_INTERACTIONS_OPENAPI_CATALOG, False),
                (GOOGLE_INTERACTIONS_MODEL_CATALOG, True),
            ],
        )
        self.assertEqual(snapshot.operation_id, "CreateInteraction")
        self.assertEqual(snapshot.model_version, "3.6-flash-07-2026")
        self.assertTrue(snapshot.streaming)
        self.assertTrue(snapshot.usage_accounting)
        self.assertTrue(snapshot.tool_calling)
        self.assertEqual(len(snapshot.catalog_snapshot_digest), 64)

    def test_catalog_rejects_endpoint_model_and_limit_drift(self) -> None:
        request = _request(GOOGLE_HOSTED_MODEL_CONFIG, final=False)
        variants = []
        missing_stream = _endpoint_schema()
        del missing_stream["components"]["schemas"][
            "CreateModelInteractionParams"
        ]["properties"]["stream"]
        variants.append((missing_stream, _model_record()))
        missing_usage = _endpoint_schema()
        del missing_usage["components"]["schemas"]["Usage"]["properties"][
            "total_tokens"
        ]
        variants.append((missing_usage, _model_record()))
        wrong_model = _model_record()
        wrong_model["name"] = "models/gemini-3.7-flash"
        variants.append((_endpoint_schema(), wrong_model))
        wrong_revision = _model_record()
        wrong_revision["version"] = "unexpected-live-revision"
        variants.append((_endpoint_schema(), wrong_revision))
        wrong_base_model = _model_record()
        wrong_base_model["baseModelId"] = "gemini-unrelated-model"
        variants.append((_endpoint_schema(), wrong_base_model))
        no_thinking = _model_record()
        no_thinking["thinking"] = False
        variants.append((_endpoint_schema(), no_thinking))
        small_output = _model_record()
        small_output["outputTokenLimit"] = 1
        variants.append((_endpoint_schema(), small_output))

        for endpoint_schema, model_record in variants:
            with self.subTest(model_record=model_record), self.assertRaisesRegex(
                GoogleInteractionsProtocolError,
                "provider_endpoint_parameters_unsupported",
            ):
                validate_google_interactions_catalog(
                    request,
                    endpoint_schema=endpoint_schema,
                    model_record=model_record,
                )

    def test_exact_name_and_revision_accept_absent_base_model_id(self) -> None:
        request = _request(GOOGLE_HOSTED_MODEL_CONFIG, final=False)
        for model_record in (
            _model_record(),
            {**_model_record(), "baseModelId": None},
        ):
            with self.subTest(base_model_id=model_record.get("baseModelId")):
                snapshot = validate_google_interactions_catalog(
                    request,
                    endpoint_schema=_endpoint_schema(),
                    model_record=model_record,
                )

                self.assertEqual(snapshot.model_name, f"models/{request.model_id}")
                self.assertEqual(snapshot.model_version, request.model_revision)

    def test_same_protocol_validates_another_model_from_request_data(self) -> None:
        request = replace(
            _request(GOOGLE_HOSTED_MODEL_CONFIG, final=False),
            model_id="gemini-data-only",
            model_revision="stable-data-only",
        )
        endpoint_schema = _endpoint_schema()
        endpoint_schema["components"]["schemas"]["ModelOption"]["enum"] = [
            "gemini-data-only"
        ]
        model_record = {
            **_model_record(),
            "name": "models/gemini-data-only",
            "baseModelId": "gemini-data-only",
            "version": "stable-data-only",
        }

        snapshot = validate_google_interactions_catalog(
            request,
            endpoint_schema=endpoint_schema,
            model_record=model_record,
        )

        self.assertEqual(snapshot.model_name, "models/gemini-data-only")
        self.assertEqual(snapshot.model_version, "stable-data-only")


def _request(model_config, *, final: bool) -> AgenticModelRequest:
    return AgenticModelRequest(
        schema_version="1",
        request_id=f"catalog-request-{'final' if final else 'explore'}",
        correlation_id="catalog-turn",
        model_id=model_config.model_id,
        model_revision=model_config.model_revision,
        model_revision_policy=model_config.model_revision_policy,
        reasoning_effort=model_config.support_flags.reasoning_efforts[-1],
        content_blocks=(
            AgenticRequestContentBlock(
                content_block_id="catalog-user",
                role="user",
                data_class="public",
                provenance="user_input",
                trust_level="trusted_actor",
                content_type="text/plain",
                content=b"synthetic request",
            ),
        ),
        tool_definitions=(
            ()
            if final
            else (
                AgenticToolDefinition(
                    "fixture_tool",
                    "Synthetic fixture tool.",
                    {"type": "object", "additionalProperties": False},
                ),
            )
        ),
        tool_results=(),
        provider_private_state=None,
        routing_constraint=google_interactions_routing_constraint(),
        max_output_tokens=1_024,
        request_phase="finalization" if final else "exploration",
    )


def _endpoint_schema() -> dict[str, object]:
    return {
        "openapi": "3.0.3",
        "info": {
            "version": "v1",
            "x-google-revision": "fixture-revision",
        },
        "servers": [
            {"url": "https://generativelanguage.googleapis.com"}
        ],
        "paths": {
            "/{api_version}/interactions": {
                "post": {
                    "operationId": "CreateInteraction",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "oneOf": [
                                        {
                                            "$ref": "#/components/schemas/CreateModelInteractionParams"
                                        }
                                    ]
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {},
                                "text/event-stream": {},
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "CreateModelInteractionParams": {
                    "required": ["input", "model"],
                    "properties": {
                        "model": {},
                        "input": {},
                        "stream": {},
                        "store": {},
                        "generation_config": {},
                        "tools": {},
                        "system_instruction": {},
                        "previous_interaction_id": {},
                        "usage": {},
                    },
                },
                "GenerationConfig": {
                    "properties": {
                        "max_output_tokens": {},
                        "thinking_summaries": {},
                        "thinking_level": {},
                    }
                },
                "ModelOption": {
                    "enum": ["gemini-3.6-flash"],
                },
                "Tool": {
                    "oneOf": [
                        {"$ref": "#/components/schemas/Function"},
                    ],
                },
                "Function": {
                    "properties": {
                        "name": {},
                        "description": {},
                        "parameters": {},
                        "type": {},
                    },
                },
                "Usage": {
                    "properties": {
                        "total_input_tokens": {},
                        "total_output_tokens": {},
                        "total_tokens": {},
                    },
                },
            }
        },
    }


def _model_record() -> dict[str, object]:
    return {
        "name": "models/gemini-3.6-flash",
        "version": "3.6-flash-07-2026",
        "inputTokenLimit": 1_048_576,
        "outputTokenLimit": 65_536,
        "supportedGenerationMethods": ["generateContent"],
        "thinking": True,
    }


if __name__ == "__main__":
    unittest.main()
