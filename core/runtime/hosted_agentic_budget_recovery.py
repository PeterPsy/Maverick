"""Validate and reconstruct durable hosted-turn budget accounting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.runtime.hosted_agentic_models import HostedAgenticLoopError


@dataclass(frozen=True)
class RestoredHostedBudgetAccounting:
    steps: int = 0
    tool_calls: int = 0
    total_tool_result_bytes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reported_cost_microusd: int = 0
    accounted_input_tokens: int = 0
    accounted_output_tokens: int = 0
    estimated_cost_microusd: int = 0


def restore_hosted_budget_accounting(
    records: Iterable[object],
    *,
    finite_cost_required: bool,
) -> RestoredHostedBudgetAccounting:
    """Return conservative counters from immutable request reservations."""
    values = RestoredHostedBudgetAccounting()
    for record in records:
        _validate_restore_record(record)
        estimated_cost = getattr(record, "budget_estimated_cost_microusd", None)
        if finite_cost_required and estimated_cost is None:
            raise HostedAgenticLoopError("provider_state_ambiguous")
        report_count = int(getattr(record, "usage_report_count", 0) or 0)
        tool_calls = int(getattr(record, "budget_tool_call_charges", 0) or 0)
        result_bytes = int(getattr(record, "budget_tool_result_bytes", 0) or 0)
        if report_count:
            input_tokens = int(getattr(record, "usage_input_tokens", 0) or 0)
            output_tokens = int(getattr(record, "usage_output_tokens", 0) or 0)
            reported_cost = getattr(record, "usage_cost_microusd", None)
            cost = (
                int(estimated_cost or 0)
                if reported_cost is None
                else int(reported_cost)
            )
            values = RestoredHostedBudgetAccounting(
                steps=values.steps + 1,
                tool_calls=values.tool_calls + tool_calls,
                total_tool_result_bytes=(
                    values.total_tool_result_bytes + result_bytes
                ),
                input_tokens=values.input_tokens + input_tokens,
                output_tokens=values.output_tokens + output_tokens,
                reported_cost_microusd=(
                    values.reported_cost_microusd
                    + (cost if reported_cost is not None else 0)
                ),
                accounted_input_tokens=(
                    values.accounted_input_tokens + input_tokens
                ),
                accounted_output_tokens=(
                    values.accounted_output_tokens + output_tokens
                ),
                estimated_cost_microusd=(
                    values.estimated_cost_microusd + cost
                ),
            )
            continue
        values = RestoredHostedBudgetAccounting(
            steps=values.steps + 1,
            tool_calls=values.tool_calls + tool_calls,
            total_tool_result_bytes=values.total_tool_result_bytes + result_bytes,
            input_tokens=values.input_tokens,
            output_tokens=values.output_tokens,
            reported_cost_microusd=values.reported_cost_microusd,
            accounted_input_tokens=(
                values.accounted_input_tokens
                + int(getattr(record, "budget_estimated_input_tokens", 0) or 0)
            ),
            accounted_output_tokens=(
                values.accounted_output_tokens
                + int(getattr(record, "request_max_output_tokens", 0) or 0)
            ),
            estimated_cost_microusd=(
                values.estimated_cost_microusd + int(estimated_cost or 0)
            ),
        )
    return values


def _validate_restore_record(record: object) -> None:
    schema_version = getattr(record, "schema_version", None)
    if schema_version is not None:
        request_control_digest = getattr(record, "request_control_digest", None)
        request_phase = getattr(record, "request_phase", None)
        request_max_output = getattr(record, "request_max_output_tokens", 0)
        estimated_input = getattr(record, "budget_estimated_input_tokens", 0)
        if (
            schema_version != "3"
            or not isinstance(request_control_digest, str)
            or len(request_control_digest) != 64
            or request_phase
            not in {"exploration", "finalization", "finalization_recovery"}
            or not _positive_integer(request_max_output)
            or not _positive_integer(estimated_input)
        ):
            raise HostedAgenticLoopError("provider_state_ambiguous")
    charges_value = getattr(record, "budget_tool_call_charges", 0)
    observed_value = getattr(record, "observed_call_count", charges_value)
    integer_values = (
        charges_value,
        observed_value,
        getattr(record, "budget_tool_result_bytes", 0),
        getattr(record, "usage_report_count", 0),
        getattr(record, "usage_input_tokens", 0),
        getattr(record, "usage_output_tokens", 0),
        getattr(record, "budget_estimated_input_tokens", 0),
        getattr(record, "request_max_output_tokens", 0),
    )
    if any(not _nonnegative_integer(value) for value in integer_values):
        raise HostedAgenticLoopError("provider_state_ambiguous")
    report_count = int(getattr(record, "usage_report_count", 0))
    charges = int(charges_value)
    observed = int(observed_value)
    estimated_cost = getattr(record, "budget_estimated_cost_microusd", None)
    usage_cost = getattr(record, "usage_cost_microusd", None)
    request_phase = getattr(record, "request_phase", "exploration")
    request_max_output = int(
        getattr(record, "request_max_output_tokens", 0) or 0
    )
    usage_input = int(getattr(record, "usage_input_tokens", 0) or 0)
    usage_output = int(getattr(record, "usage_output_tokens", 0) or 0)
    if (
        report_count not in {0, 1}
        or charges > observed
        or (request_phase != "exploration" and charges != 0)
        or (report_count == 0 and (usage_input != 0 or usage_output != 0))
        or (report_count == 0 and usage_cost is not None)
        or (report_count == 1 and usage_output > request_max_output)
        or any(
            value is not None and not _nonnegative_integer(value)
            for value in (estimated_cost, usage_cost)
        )
    ):
        raise HostedAgenticLoopError("provider_state_ambiguous")


def _positive_integer(value: object) -> bool:
    return _nonnegative_integer(value) and int(value) > 0


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
