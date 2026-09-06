"""Real Google codec and preflight, simulated HTTPS: no unobserved tuple may pass."""

import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from unittest import TestCase, mock

from core.providers.certification_live_receipt import validate_live_probe_receipt
from core.providers.certification_target import builtin_api_certification_target
from core.providers.errors import CapabilityCertificateError
from core.providers.google_interactions_models import GoogleInteractionsProtocolError
from core.providers.google_interactions_probe_contract import PROBE_TOOL_NAME
from core.providers.google_interactions_transport import GOOGLE_INTERACTIONS_ENDPOINT
from core.runtime.execution_binding import canonical_digest
from scripts import run_google_interactions_probe as runner
from tests.unit.providers.test_google_interactions_catalog import _endpoint_schema, _model_record
from tests.unit.providers.test_google_interactions_codec import _ScriptedTransport, _text_stream, _tool_stream


class GoogleProbeCatalogReceiptTest(TestCase):
    def run_probe(self, *, fault=None, fault_request=0):
        transport = _ScriptedTransport([
            *[_tool_stream(
                f"interaction-{ordinal}", tool_name=PROBE_TOOL_NAME, call_id=f"call-{ordinal}",
                arguments={"path": ".", "max_depth": 1, "max_results": 10},
            ) for ordinal in (1, 2)],
            _text_stream("interaction-3", "OK"),
        ])
        transport.endpoint = GOOGLE_INTERACTIONS_ENDPOINT
        catalog_calls = []

        def fetch(url, credential):
            index = len(transport.payloads)
            catalog_calls.append((index, url, credential is not None))
            if index == fault_request and fault == "unavailable":
                raise GoogleInteractionsProtocolError("provider_unavailable")
            schema, model = _endpoint_schema(), _model_record()
            if index == fault_request:
                if fault == "missing_schema":
                    schema = None
                elif fault == "missing_model":
                    model = None
                elif fault == "revision":
                    model["version"] = "not-the-certified-revision"
                elif fault == "streaming":
                    del schema["components"]["schemas"]["CreateModelInteractionParams"]["properties"]["stream"]
                elif fault == "catalog_drift":
                    schema["info"]["x-google-revision"] = "changed-during-probe"
                elif fault == "small_context":
                    model["inputTokenLimit"] = 16_384
            return schema if credential is None else model

        output = StringIO()
        with mock.patch.dict("os.environ", {
            "MAVERICK_GOOGLE_CERTIFICATION_API_KEY": "synthetic-secret",
            "MAVERICK_CERTIFICATION_ALLOW_LIVE": "1",
            "MAVERICK_CERTIFICATION_MAX_COST_MICROUSD": "10000000",
            "MAVERICK_CERTIFICATION_PROBE_INTERVAL_SECONDS": "0",
            "MAVERICK_CERTIFICATION_RUN_NONCE": "1" * 32,
        }), mock.patch("core.providers.google_interactions_catalog._fetch_catalog", side_effect=fetch), mock.patch(
            "core.providers.google_interactions_transport.GoogleInteractionsHttpTransport", return_value=transport,
        ), redirect_stdout(output):
            exit_code = asyncio.run(runner._main())
        self.assertNotIn("synthetic-secret", output.getvalue())
        receipt = json.loads(output.getvalue())
        self.assertEqual(exit_code == 0, receipt["succeeded"])
        return receipt, transport, catalog_calls

    def validate(self, receipt):
        return validate_live_probe_receipt(
            receipt, provider_id="google-ai-studio",
            target_digest=builtin_api_certification_target("google-ai-studio"), run_nonce="1" * 32,
        )

    def test_real_runner_preflights_each_request_and_binds_observed_catalog(self):
        receipt, transport, calls = self.run_probe()
        self.assertTrue(receipt["succeeded"])
        self.assertEqual(len(transport.payloads), 3)
        self.assertEqual(len(calls), 6)
        for ordinal in range(3):
            self.assertCountEqual([authenticated for index, _, authenticated in calls if index == ordinal], [True, False])
        self.assertEqual(len(receipt["catalog_snapshots"]), 3)
        for snapshot in receipt["catalog_snapshots"]:
            self.assertEqual(snapshot["api_version"], "v1")
            self.assertEqual(snapshot["model_version"], "stable-2026-07")
            for key in ("endpoint_schema_digest", "model_record_digest", "catalog_snapshot_digest"):
                self.assertEqual(len(snapshot[key]), 64)
        self.assertEqual(self.validate(receipt), receipt)

    def test_missing_incompatible_or_unavailable_catalog_never_reaches_transport(self):
        for fault in ("missing_schema", "missing_model", "revision", "streaming", "unavailable", "small_context"):
            with self.subTest(fault=fault):
                receipt, transport, _ = self.run_probe(fault=fault)
                self.assertFalse(receipt["succeeded"])
                self.assertEqual(transport.payloads, [])
                self.assertEqual(receipt["request_count"], 0)
                self.assertEqual(receipt["catalog_snapshots"], [])
                self.assertEqual(receipt["target_digest"], "")
                with self.assertRaises(CapabilityCertificateError):
                    self.validate(receipt)

    def test_catalog_drift_and_last_request_preflight_failure_cannot_pass(self):
        for fault, ordinal in (("catalog_drift", 1), ("revision", 2)):
            with self.subTest(fault=fault):
                receipt, transport, calls = self.run_probe(fault=fault, fault_request=ordinal)
                self.assertFalse(receipt["succeeded"])
                self.assertEqual(len(transport.payloads), ordinal)
                self.assertEqual(receipt["request_count"], ordinal)
                self.assertEqual(len(calls), (ordinal + 1) * 2)
                with self.assertRaises(CapabilityCertificateError):
                    self.validate(receipt)

    def test_rehashed_receipts_cannot_omit_relabel_or_mix_catalog_observations(self):
        receipt, _, _ = self.run_probe()
        for fault in ("missing", "partial", "revision", "api", "digest", "mixed", "boolean", "limits", "extra"):
            candidate = deepcopy(receipt)
            observations = candidate["catalog_snapshots"]
            if fault == "missing":
                del candidate["catalog_snapshots"]
            elif fault == "partial":
                observations.pop()
            else:
                field, value = {
                    "revision": ("model_version", "unverified"), "api": ("api_version", "v2"),
                    "digest": ("model_record_digest", "invalid"), "mixed": ("model_record_digest", "a" * 64),
                    "boolean": ("streaming", 1), "limits": ("output_token_limit", 2048),
                    "extra": ("unreviewed_data", "not-allowed"),
                }[fault]
                observations[-1][field] = value
                observations[-1]["catalog_snapshot_digest"] = canonical_digest({
                    key: value for key, value in observations[-1].items() if key != "catalog_snapshot_digest"
                })
            candidate["result_summary_digest"] = canonical_digest({
                key: value for key, value in candidate.items()
                if key not in {"succeeded", "target_digest", "run_nonce", "test_run_id", "result_summary_digest"}
            })
            with self.subTest(fault=fault), self.assertRaises(CapabilityCertificateError):
                self.validate(candidate)
