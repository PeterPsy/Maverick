#!/usr/bin/env python3
"""Create and verify redaction-safe physical-device PWA regression evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any


EVIDENCE_SCHEMA = "maverick.pwa-cache-device-regression.v1"
SMOKE_SCHEMA = "maverick.pwa-physical-browser-smoke.v1"
WAIVER_SCHEMA = "maverick.pwa-cache-device-regression-waiver.v1"
RELEASE_CANDIDATE_BINDING = "exact_release_id"
POLICY_PATH = Path("docs/product/pwa_cache_operational_policy.v1.json")
PASS = "pass"
PROHIBITED_KEYS = re.compile(
    r"(^|_)(content|email|file_name|filename|record_id|serial|subject|token|url|user_id|username)($|_)",
    re.IGNORECASE,
)
HTTP_VALUE = re.compile(r"https?://", re.IGNORECASE)
RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+@:-]{0,127}$")


def evidence_template(policy: dict[str, Any], release_id: str) -> dict[str, Any]:
    if not valid_release_id(release_id):
        raise ValueError("release_id must identify one bounded release candidate")
    profiles = policy["device_regression"]["required_profiles"]
    return {
        "schema": EVIDENCE_SCHEMA,
        "captured_at": None,
        "environment": "physical-device",
        "redaction_reviewed": False,
        "release_id": release_id,
        "runs": [
            {
                "profile": profile,
                "os_version": "replace",
                "browser_version": "replace",
                "scenarios": {scenario: "pending" for scenario in scenarios_for_profile(policy, profile)},
            }
            for profile in profiles
        ],
    }


def merge_smoke_progress(
    policy: dict[str, Any],
    release_id: str,
    smoke_payloads: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Merge truthful smoke outcomes into a still-verifiable matrix draft."""
    matrix = evidence_template(policy, release_id)
    runs = {run["profile"]: run for run in matrix["runs"]}
    observed_profiles: set[str] = set()
    captured: list[datetime] = []
    imported = 0
    for index, payload in enumerate(smoke_payloads):
        if payload.get("schema") != SMOKE_SCHEMA:
            continue
        label = f"smoke[{index}]"
        if payload.get("release_id") != release_id:
            raise ValueError(f"{label} release_id does not match the requested candidate")
        if payload.get("environment") != "physical-device":
            raise ValueError(f"{label} is not physical-device evidence")
        if payload.get("redaction_reviewed") is not True:
            raise ValueError(f"{label} has not passed redaction review")
        profile = payload.get("profile")
        if not isinstance(profile, str) or profile not in runs:
            raise ValueError(f"{label} profile is not in the required matrix")
        if profile in observed_profiles:
            raise ValueError(f"{label} duplicates profile {profile}")
        observed_profiles.add(profile)
        timestamp = parse_timestamp(payload.get("captured_at"))
        if timestamp is None:
            raise ValueError(f"{label} captured_at is invalid")
        captured.append(timestamp)
        source_scenarios = payload.get("scenarios")
        if not isinstance(source_scenarios, dict):
            raise ValueError(f"{label} scenarios must be an object")
        target = runs[profile]
        for field in ("os_version", "browser_version"):
            value = payload.get(field)
            if not bounded_text(value, 128):
                raise ValueError(f"{label} {field} is invalid")
            target[field] = value
        for scenario in target["scenarios"]:
            outcome = source_scenarios.get(scenario, "not-run")
            if outcome not in {"pass", "fail", "not-run"}:
                raise ValueError(f"{label} scenario {scenario} has an invalid outcome")
            target["scenarios"][scenario] = "pending" if outcome == "not-run" else outcome
            if outcome in {"pass", "fail"}:
                imported += 1
    if captured:
        matrix["captured_at"] = min(captured).astimezone(timezone.utc).isoformat()
        matrix["redaction_reviewed"] = True
    outcomes = [outcome for run in matrix["runs"] for outcome in run["scenarios"].values()]
    summary = {
        "profiles_imported": len(observed_profiles),
        "results_imported": imported,
        "pass": outcomes.count("pass"),
        "fail": outcomes.count("fail"),
        "pending": outcomes.count("pending"),
        "total": len(outcomes),
    }
    return matrix, summary


def validate_evidence(
    payload: Any,
    policy: dict[str, Any],
    *,
    expected_release_id: str,
    now: datetime | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["evidence must be a JSON object"]
    reject_sensitive_fields(payload, errors)
    reject_unexpected_fields(
        payload,
        {"captured_at", "environment", "redaction_reviewed", "release_id", "runs", "schema"},
        "evidence",
        errors,
    )
    if payload.get("schema") != EVIDENCE_SCHEMA:
        errors.append(f"schema must be {EVIDENCE_SCHEMA}")
    if payload.get("environment") != "physical-device":
        errors.append("environment must be physical-device; emulation is not release evidence")
    if payload.get("redaction_reviewed") is not True:
        errors.append("redaction_reviewed must be true")
    release_id = payload.get("release_id")
    if not valid_release_id(expected_release_id):
        errors.append("expected_release_id must identify one bounded release candidate")
    if not valid_release_id(release_id):
        errors.append("release_id must identify one bounded release candidate")
    elif valid_release_id(expected_release_id) and release_id != expected_release_id:
        errors.append("release_id does not match the expected release candidate")
    captured_at = parse_timestamp(payload.get("captured_at"))
    if captured_at is None:
        errors.append("captured_at must be an ISO-8601 timestamp with timezone")
    else:
        current = now or datetime.now(timezone.utc)
        current = current.astimezone(timezone.utc)
        max_age = policy["device_regression"]["max_evidence_age_days"]
        if captured_at > current + timedelta(minutes=5):
            errors.append("captured_at cannot be in the future")
        elif current - captured_at > timedelta(days=max_age):
            errors.append(f"physical-device evidence is older than {max_age} days")
    audit_runs(payload.get("runs"), policy, errors)
    return errors


def validate_release_evidence(
    payload: Any,
    policy: dict[str, Any],
    *,
    expected_release_id: str,
    waiver: Any | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Enforce the strict matrix or an exact, active release-owner waiver."""
    strict_errors = validate_evidence(
        payload,
        policy,
        expected_release_id=expected_release_id,
        now=now,
    )
    if waiver is None:
        return strict_errors
    waiver_errors = validate_waiver(
        waiver,
        payload,
        policy,
        expected_release_id=expected_release_id,
        now=now,
    )
    if waiver_errors:
        return [*strict_errors, *waiver_errors]
    return [error for error in strict_errors if " has non-passing scenarios:" not in error]


def validate_waiver(
    waiver: Any,
    evidence: Any,
    policy: dict[str, Any],
    *,
    expected_release_id: str,
    now: datetime | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(waiver, dict):
        return ["waiver must be a JSON object"]
    reject_unexpected_fields(
        waiver,
        {
            "accepted_at",
            "expires_at",
            "observed_results",
            "release_id",
            "release_owner_approved",
            "risk_acceptance",
            "schema",
            "scope",
        },
        "waiver",
        errors,
    )
    if waiver.get("schema") != WAIVER_SCHEMA:
        errors.append(f"waiver schema must be {WAIVER_SCHEMA}")
    if waiver.get("scope") != "single-release-candidate":
        errors.append("waiver scope must be single-release-candidate")
    if waiver.get("release_owner_approved") is not True:
        errors.append("waiver release_owner_approved must be true")
    if waiver.get("risk_acceptance") != "remaining-physical-coverage":
        errors.append("waiver risk_acceptance is invalid")
    release_id = waiver.get("release_id")
    if release_id != expected_release_id:
        errors.append("waiver release_id does not match the expected release candidate")
    if isinstance(evidence, dict) and release_id != evidence.get("release_id"):
        errors.append("waiver release_id does not match the evidence release candidate")

    accepted_at = parse_timestamp(waiver.get("accepted_at"))
    expires_at = parse_timestamp(waiver.get("expires_at"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    max_days = policy["device_regression"].get("max_waiver_age_days")
    if accepted_at is None:
        errors.append("waiver accepted_at must be an ISO-8601 timestamp with timezone")
    if expires_at is None:
        errors.append("waiver expires_at must be an ISO-8601 timestamp with timezone")
    if accepted_at is not None and accepted_at > current + timedelta(minutes=5):
        errors.append("waiver accepted_at cannot be in the future")
    if accepted_at is not None and expires_at is not None:
        if expires_at <= accepted_at:
            errors.append("waiver expires_at must be later than accepted_at")
        elif not positive_integer(max_days) or expires_at - accepted_at > timedelta(days=max_days):
            errors.append("waiver exceeds the policy maximum lifetime")
        if current > expires_at:
            errors.append("waiver has expired")
    evidence_captured_at = parse_timestamp(evidence.get("captured_at")) if isinstance(evidence, dict) else None
    if accepted_at is not None and evidence_captured_at is not None and accepted_at < evidence_captured_at:
        errors.append("waiver must be accepted after the evidence was captured")

    observed = waiver.get("observed_results")
    if not isinstance(observed, dict):
        errors.append("waiver observed_results must be an object")
        observed = {}
    else:
        reject_unexpected_fields(observed, {"fail", "pass", "pending", "total"}, "waiver.observed_results", errors)
    for field in ("pass", "fail", "pending", "total"):
        value = observed.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"waiver observed_results.{field} must be a non-negative integer")

    counts, unsupported = evidence_outcome_counts(evidence)
    if unsupported:
        errors.append("waiver can cover only literal pass and pending outcomes")
    if counts["fail"]:
        errors.append("waiver cannot cover failed physical-device outcomes")
    if counts["pass"] == 0 or counts["pending"] == 0:
        errors.append("waiver requires both observed passes and explicitly pending coverage")
    if observed != counts:
        errors.append("waiver observed_results do not match the physical-device evidence")
    return errors


def evidence_outcome_counts(payload: Any) -> tuple[dict[str, int], int]:
    values: list[Any] = []
    if isinstance(payload, dict) and isinstance(payload.get("runs"), list):
        for run in payload["runs"]:
            if isinstance(run, dict) and isinstance(run.get("scenarios"), dict):
                values.extend(run["scenarios"].values())
    counts = {
        "pass": values.count("pass"),
        "fail": values.count("fail"),
        "pending": values.count("pending"),
        "total": len(values),
    }
    unsupported = sum(value not in {"pass", "fail", "pending"} for value in values)
    return counts, unsupported


def audit_runs(value: Any, policy: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append("runs must be an array")
        return
    required_profiles = set(policy["device_regression"]["required_profiles"])
    observed: set[str] = set()
    for index, run in enumerate(value):
        label = f"runs[{index}]"
        if not isinstance(run, dict):
            errors.append(f"{label} must be an object")
            continue
        reject_unexpected_fields(
            run,
            {"browser_version", "os_version", "profile", "scenarios"},
            label,
            errors,
        )
        profile = run.get("profile")
        if not isinstance(profile, str) or profile not in required_profiles:
            errors.append(f"{label}.profile is not in the required matrix")
            continue
        if profile in observed:
            errors.append(f"{label}.profile is duplicated")
        observed.add(profile)
        required_scenarios = set(scenarios_for_profile(policy, profile))
        for field in ("os_version", "browser_version"):
            if not bounded_text(run.get(field), 128):
                errors.append(f"{label}.{field} must be a bounded string")
        scenarios = run.get("scenarios")
        if not isinstance(scenarios, dict):
            errors.append(f"{label}.scenarios must be an object")
            continue
        missing = required_scenarios - scenarios.keys()
        unexpected = scenarios.keys() - required_scenarios
        if missing:
            errors.append(f"{label} is missing scenarios: {', '.join(sorted(missing))}")
        if unexpected:
            errors.append(f"{label} has unexpected scenarios: {', '.join(sorted(unexpected))}")
        failed = sorted(name for name in required_scenarios if scenarios.get(name) != PASS)
        if failed:
            errors.append(f"{label} has non-passing scenarios: {', '.join(failed)}")
    missing_profiles = required_profiles - observed
    if missing_profiles:
        errors.append(f"missing physical-device profiles: {', '.join(sorted(missing_profiles))}")


def reject_sensitive_fields(value: Any, errors: list[str], path: str = "evidence") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if PROHIBITED_KEYS.search(str(key)):
                errors.append(f"{path}.{key}: sensitive diagnostic field is prohibited")
            reject_sensitive_fields(child, errors, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_fields(child, errors, f"{path}[{index}]")
    elif isinstance(value, str) and HTTP_VALUE.search(value):
        errors.append(f"{path}: URLs are prohibited in device evidence")


def reject_unexpected_fields(
    value: dict[str, Any],
    allowed: set[str],
    path: str,
    errors: list[str],
) -> None:
    for key in sorted(set(value) - allowed):
        errors.append(f"{path}.{key}: unexpected evidence field is prohibited")


def load_policy(root: Path) -> dict[str, Any]:
    payload = json.loads((root / POLICY_PATH).read_text(encoding="utf-8"))
    device = payload.get("device_regression")
    if not isinstance(device, dict):
        raise ValueError("operational policy has no device_regression contract")
    if not positive_integer(device.get("max_evidence_age_days")):
        raise ValueError("device regression max evidence age is invalid")
    if not positive_integer(device.get("max_waiver_age_days")):
        raise ValueError("device regression max waiver age is invalid")
    if device.get("release_candidate_binding") != RELEASE_CANDIDATE_BINDING:
        raise ValueError("device regression must require exact release_id candidate binding")
    for field in ("required_profiles", "required_scenarios"):
        values = device.get(field)
        if (not isinstance(values, list) or not values or not all(bounded_text(item, 128) for item in values)
                or len(values) != len(set(values))):
            raise ValueError(f"device regression {field} is invalid")
    profiles = set(device["required_profiles"])
    profile_scenarios = device.get("profile_scenarios", {})
    if not isinstance(profile_scenarios, dict) or not set(profile_scenarios).issubset(profiles):
        raise ValueError("device regression profile_scenarios has an unknown profile")
    for profile, scenarios in profile_scenarios.items():
        if (not isinstance(scenarios, list) or not all(bounded_text(item, 128) for item in scenarios)
                or len(scenarios) != len(set(scenarios))):
            raise ValueError(f"device regression scenarios for {profile} are invalid")
    return payload


def scenarios_for_profile(policy: dict[str, Any], profile: str) -> list[str]:
    device = policy["device_regression"]
    common = device["required_scenarios"]
    additional = device.get("profile_scenarios", {}).get(profile, [])
    return list(dict.fromkeys([*common, *additional]))


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def bounded_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and value.strip() == value and 0 < len(value) <= limit


def valid_release_id(value: Any) -> bool:
    return isinstance(value, str) and RELEASE_ID.fullmatch(value) is not None


def positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    template = subparsers.add_parser("template", help="write a matrix template")
    template.add_argument("--output", required=True, type=Path)
    template.add_argument("--release-id", required=True)
    verify = subparsers.add_parser("verify", help="enforce the physical-device release gate")
    verify.add_argument("--input", required=True, type=Path)
    verify.add_argument("--expected-release-id", required=True)
    verify.add_argument("--waiver", type=Path)
    progress = subparsers.add_parser("progress", help="merge physical smoke diaries into a matrix draft")
    progress.add_argument("--smoke-dir", required=True, type=Path)
    progress.add_argument("--output", required=True, type=Path)
    progress.add_argument("--release-id", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    try:
        policy = load_policy(root)
        if args.command == "template":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(evidence_template(policy, args.release_id), indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Wrote physical-device matrix template to {args.output}")
            return 0
        if args.command == "progress":
            smoke_payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(args.smoke_dir.glob("*.json"))
            ]
            payload, summary = merge_smoke_progress(policy, args.release_id, smoke_payloads)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(
                "PWA physical-device progress: "
                f"{summary['pass']} pass, {summary['fail']} fail, "
                f"{summary['pending']} pending ({summary['total']} total); "
                f"wrote {args.output}"
            )
            return 0
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        waiver = json.loads(args.waiver.read_text(encoding="utf-8")) if args.waiver else None
        errors = validate_release_evidence(
            payload,
            policy,
            expected_release_id=args.expected_release_id,
            waiver=waiver,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"PWA device regression: {error}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"PWA device regression: {error}", file=sys.stderr)
        return 1
    if args.waiver:
        counts, _ = evidence_outcome_counts(payload)
        print(
            "PWA physical-device release waiver is current and exact-candidate-bound: "
            f"{counts['pass']} pass, {counts['fail']} fail, {counts['pending']} pending."
        )
    else:
        print("PWA physical-device regression evidence matches the release candidate and is current and complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
