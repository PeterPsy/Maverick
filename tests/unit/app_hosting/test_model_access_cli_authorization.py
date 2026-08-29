"""Tests for trusted Core authorization of native CLI model selection."""

from __future__ import annotations

import unittest

from core.model_access.cli_authorization import authorize_cli_invocation
from core.model_access.models import ModelAccessCatalog, ModelAccessModel


def _catalog(*, available: bool = True) -> ModelAccessCatalog:
    model = ModelAccessModel(
        model_id="gpt-workspace",
        label="Workspace model",
        provider_id="codex",
        transport="cli",
        available=available,
    )
    return ModelAccessCatalog(
        api_models=(),
        cli_models=(model,),
        cli_defaults={"codex": model.model_id},
    )


class ModelAccessCliAuthorizationTests(unittest.TestCase):
    def test_non_diagnostic_execution_requires_exactly_one_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one model"):
            authorize_cli_invocation(
                _catalog(),
                provider_id="codex",
                argv=("exec", "--json"),
            )
        with self.assertRaisesRegex(ValueError, "exactly one model"):
            authorize_cli_invocation(
                _catalog(),
                provider_id="codex",
                argv=("exec", "--model", "gpt-workspace", "--model", "gpt-workspace"),
            )

    def test_model_must_be_available_in_the_provider_scoped_catalog(self) -> None:
        for catalog, model_id in (
            (_catalog(), "gpt-other-workspace"),
            (_catalog(available=False), "gpt-workspace"),
        ):
            with self.subTest(model_id=model_id, available=catalog.cli_models[0].available):
                with self.assertRaisesRegex(PermissionError, "scoped catalog"):
                    authorize_cli_invocation(
                        catalog,
                        provider_id="codex",
                        argv=("exec", "--model", model_id),
                    )

    def test_only_bounded_diagnostics_may_omit_the_model(self) -> None:
        for argv in (("--version",), ("debug", "models"), ("login", "status")):
            with self.subTest(argv=argv):
                self.assertIsNone(
                    authorize_cli_invocation(
                        _catalog(),
                        provider_id="codex",
                        argv=argv,
                    )
                )


if __name__ == "__main__":
    unittest.main()
