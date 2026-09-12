"""Live result-authority guard for rollback-safe hosted workspace effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.egress.classification import CanonicalSourceClassification
from core.runtime.tool_catalog import RuntimeToolSurfaceResult
from core.runtime.tool_errors import RuntimeToolError


@dataclass(frozen=True)
class HostedResultAuthorityGuard:
    """Re-resolve one exact policy-admitted result around an overlay commit."""

    resolver: object
    handle: str
    arguments: dict[str, object]
    payload: dict[str, object]
    context: object
    expected_classification: CanonicalSourceClassification
    allowed_data_classes: tuple[str, ...] = ("public",)
    allowed_data_classes_resolver: Callable[[], tuple[str, ...]] | None = None

    def verify_before(self) -> None:
        self._verify()

    def verify_after(self) -> None:
        self._verify()

    def _verify(self) -> None:
        if not callable(self.resolver):
            raise RuntimeToolError("tool_result_egress_not_guaranteed")
        allowed_data_classes = self.allowed_data_classes
        if self.allowed_data_classes_resolver is not None:
            try:
                live = self.allowed_data_classes_resolver()
            except Exception:
                live = ()
            if not isinstance(live, tuple) or any(
                not isinstance(item, str) for item in live
            ):
                live = ()
            live_set = set(live)
            allowed_data_classes = tuple(
                item for item in allowed_data_classes if item in live_set
            )
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
            or resolved.classification.data_class not in allowed_data_classes
        ):
            raise RuntimeToolError("tool_result_egress_not_guaranteed")


__all__ = ["HostedResultAuthorityGuard"]
