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
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        errors = validate_evidence(
            payload,
            policy,
            expected_release_id=args.expected_release_id,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(f"PWA device regression: {error}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"PWA device regression: {error}", file=sys.stderr)
        return 1
    print("PWA physical-device regression evidence matches the release candidate and is current and complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
