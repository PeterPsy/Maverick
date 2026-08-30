from __future__ import annotations

from unittest.mock import patch
import unittest

from core.providers.agentic_protocol import EphemeralCredential
from core.providers.google_interactions_catalog import (
    GOOGLE_INTERACTIONS_MODEL_CATALOG,
    GOOGLE_INTERACTIONS_OPENAPI_CATALOG,
    preflight_google_interactions_catalog,
    validate_google_interactions_catalog,
)
from core.providers.google_interactions_models import GoogleInteractionsProtocolError
from core.runtime.hosted_harness_recipes import GOOGLE_GOVERNED_WORKSPACE_RECIPE
from tests.unit.providers.test_hosted_harness_recipes import _request


class GoogleInteractionsCatalogTest(unittest.TestCase):
    def test_live_preflight_fetches_both_exact_catalogs(self) -> None:
        calls: list[tuple[str, bool]] = []

        def fetch(url, credential):
            calls.append((url, credential is not None))
            return _endpoint_schema() if credential is None else _model_record()

        request = _request(GOOGLE_GOVERNED_WORKSPACE_RECIPE, final=False)
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
        self.assertEqual(snapshot.model_version, "stable-2026-07")
        self.assertTrue(snapshot.streaming)
        self.assertTrue(snapshot.usage_accounting)
        self.assertTrue(snapshot.tool_calling)
        self.assertEqual(len(snapshot.catalog_snapshot_digest), 64)

    def test_catalog_rejects_endpoint_model_and_limit_drift(self) -> None:
        request = _request(GOOGLE_GOVERNED_WORKSPACE_RECIPE, final=False)
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
        "baseModelId": "gemini-3.6-flash",
        "version": "stable-2026-07",
        "inputTokenLimit": 1_048_576,
        "outputTokenLimit": 65_536,
        "supportedGenerationMethods": ["generateContent"],
        "thinking": True,
    }


if __name__ == "__main__":
    unittest.main()
