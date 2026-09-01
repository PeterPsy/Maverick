from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace
import unittest

from core.egress.classification import fail_closed_classification, validated_classification
from core.runtime.confined_filesystem import FilesystemResourceObservation
from core.runtime.filesystem_mutation_lineage import resolve_filesystem_mutation_lineage
from core.runtime.tool_private_payloads import canonical_tool_arguments


NOW = datetime(2026, 8, 28, tzinfo=UTC)


class _Ledger:
    def __init__(self, records, results, *, artifacts=None, fail_load=False):
        self._records = list(records)
        self._results = dict(results)
        self._artifacts = dict(artifacts or {})
        self._fail_load = fail_load
        for record in self._records:
            result = self._results[record.invocation_id]
            digest = hashlib.sha256(canonical_tool_arguments(result)).hexdigest()
            record.result_source_revision = digest
            record.result_source_digest = digest
            artifact = self._artifacts.get(record.invocation_id)
            if artifact is not None:
                record.result_artifact_sha256 = hashlib.sha256(artifact).hexdigest()
                record.result_artifact_size_bytes = len(artifact)
        self.store = SimpleNamespace(
            list_tool_invocations=self._list_tool_invocations
        )

    def _list_tool_invocations(self, *, session_id):
        return [
            record
            for record in self._records
            if record.session_id == session_id
        ]

    def load_result(self, record):
        if self._fail_load:
            raise RuntimeError("unavailable")
        return self._results[record.invocation_id]

    def load_result_artifact(self, record):
        return self._artifacts[record.invocation_id]


class FilesystemMutationLineageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.observation = FilesystemResourceObservation(
            workspace_id="default",
            resource_kind="filesystem_file",
            resource_ref="notes/public.txt",
            resource_identity="linux:1:2",
            resource_revision="a" * 64,
            resource_digest="a" * 64,
        )
        self.fallback = fail_closed_classification(
            provenance="tool_result",
            source_ref=self.observation.resource_ref,
            source_revision=self.observation.resource_revision,
            source_digest=self.observation.resource_digest,
            resource_identity=self.observation.resource_identity,
        )

    def test_exact_successful_write_rebinds_taint_for_rebuilt_resolver(self) -> None:
        record = self._record(data_class="public")
        resolved = self._resolve(
            self.fallback,
            _Ledger([record], {record.invocation_id: self._result()}),
        )

        self.assertEqual(resolved.data_class, "public")
        self.assertEqual(resolved.source_ref, self.observation.resource_ref)
        self.assertEqual(
            resolved.source_revision,
            self.observation.resource_revision,
        )
        self.assertEqual(
            resolved.resource_identity,
            self.observation.resource_identity,
        )
        self.assertEqual(resolved.classification_revision, 1)

    def test_move_uses_exact_destination_postimage(self) -> None:
        record = self._record(
            handle="core-capability:filesystem.move",
            data_class="workspace_internal",
        )
        result = {
            **self._result(),
            "source_path": "notes/source.txt",
            "destination_path": self.observation.resource_ref,
        }
        result.pop("path")

        resolved = self._resolve(
            self.fallback,
            _Ledger([record], {record.invocation_id: result}),
        )

        self.assertEqual(resolved.data_class, "workspace_internal")

    def test_authoritative_and_lineage_classes_join_restrictively(self) -> None:
        authority = self._classification("public", trust="trusted_actor")
        record = self._record(
            data_class="regulated_or_customer_data",
            trust="untrusted_tool_output",
        )

        resolved = self._resolve(
            authority,
            _Ledger([record], {record.invocation_id: self._result()}),
        )

        self.assertEqual(resolved.data_class, "regulated_or_customer_data")
        self.assertEqual(resolved.trust_level, "untrusted_tool_output")

    def test_incomplete_exact_lineage_cannot_promote_unclassified_resource(self) -> None:
        record = self._record(data_class="public", classification_revision=None)

        resolved = self._resolve(
            self.fallback,
            _Ledger([record], {record.invocation_id: self._result()}),
        )

        self.assertEqual(resolved.data_class, "unclassified")
        self.assertIsNone(resolved.classification_revision)

    def test_compacted_result_uses_verified_original_artifact(self) -> None:
        record = self._record(data_class="public", artifact=True)
        original = json.dumps(self._result()).encode("utf-8")
        ledger = _Ledger(
            [record],
            {record.invocation_id: {"artifact_ref": "private:result"}},
            artifacts={record.invocation_id: original},
        )

        resolved = self._resolve(self.fallback, ledger)

        self.assertEqual(resolved.data_class, "public")

    def test_unreadable_mutation_evidence_fails_closed(self) -> None:
        record = self._record(data_class="public")
        authority = self._classification("public", trust="trusted_actor")

        resolved = self._resolve(
            authority,
            _Ledger(
                [record],
                {record.invocation_id: self._result()},
                fail_load=True,
            ),
        )

        self.assertEqual(resolved.data_class, "unclassified")
        self.assertIsNone(resolved.classification_revision)

    def test_result_digest_mismatch_fails_closed(self) -> None:
        record = self._record(data_class="public")
        ledger = _Ledger([record], {record.invocation_id: self._result()})
        record.result_source_digest = "0" * 64

        resolved = self._resolve(
            self._classification("public", trust="trusted_actor"),
            ledger,
        )

        self.assertEqual(resolved.data_class, "unclassified")
        self.assertIsNone(resolved.classification_revision)

    def _resolve(self, authoritative, ledger):
        return resolve_filesystem_mutation_lineage(
            observation=self.observation,
            provenance="tool_result",
            authoritative=authoritative,
            ledger=ledger,
            session_id="session-1",
        )

    def _record(
        self,
        *,
        handle="core-capability:filesystem.write",
        data_class,
        trust="trusted_actor",
        classification_revision=1,
        artifact=False,
    ):
        return SimpleNamespace(
            invocation_id=f"invocation-{handle}",
            workspace_id="default",
            session_id="session-1",
            state="succeeded",
            resolved_tool_handle=handle,
            result_data_class=data_class,
            result_trust_level=trust,
            result_provenance="tool_result",
            result_classification_revision=classification_revision,
            result_classification_authority_id="",
            result_classification_authority_kind="",
            result_classification_authority_ref="",
            result_classification_authority_revision=None,
            result_classification_authority_digest="",
            result_classification_authority_policy_revision="",
            result_classification_authority_bound=False,
            result_artifact_private_ref=("private:artifact" if artifact else None),
        )

    def _result(self):
        return {
            "path": self.observation.resource_ref,
            "resource_identity": self.observation.resource_identity,
            "resource_revision": self.observation.resource_revision,
            "resource_digest": self.observation.resource_digest,
        }

    def _classification(self, data_class, *, trust):
        return validated_classification(
            data_class=data_class,
            provenance="tool_result",
            trust_level=trust,
            source_ref=self.observation.resource_ref,
            source_revision=self.observation.resource_revision,
            source_digest=self.observation.resource_digest,
            resource_identity=self.observation.resource_identity,
            classification_revision=1,
        )


if __name__ == "__main__":
    unittest.main()
