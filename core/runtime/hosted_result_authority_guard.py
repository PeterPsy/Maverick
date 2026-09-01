"""Live result-authority guard for rollback-safe hosted workspace effects."""

from __future__ import annotations

from dataclasses import dataclass

from core.egress.classification import CanonicalSourceClassification
from core.runtime.tool_catalog import RuntimeToolSurfaceResult
from core.runtime.tool_errors import RuntimeToolError


@dataclass(frozen=True)
class HostedResultAuthorityGuard:
    """Re-resolve one exact public result immediately around an overlay commit."""

    resolver: object
    handle: str
    arguments: dict[str, object]
    payload: dict[str, object]
    context: object
    expected_classification: CanonicalSourceClassification

    def verify_before(self) -> None:
        self._verify()

    def verify_after(self) -> None:
        self._verify()

    def _verify(self) -> None:
        if not callable(self.resolver):
            raise RuntimeToolError("tool_result_egress_not_guaranteed")
        try:
            resolved = self.resolver(
                self.handle,
                self.arguments,
                self.payload,
                self.context,
            )
        except Exception as error:
            raise RuntimeToolError(
                "tool_result_egress_not_guaranteed"
            ) from error
        if (
            not isinstance(resolved, RuntimeToolSurfaceResult)
            or resolved.payload != self.payload
            or resolved.classification != self.expected_classification
            or resolved.classification.data_class != "public"
        ):
            raise RuntimeToolError("tool_result_egress_not_guaranteed")


__all__ = ["HostedResultAuthorityGuard"]
