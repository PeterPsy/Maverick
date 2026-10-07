"""Content-free native result facts; transport success is not media validity."""

import json
import re


_FAILURE_OUTCOMES = {
    "MC-PEEKABOO-20": "dispatched_unverified",
    "MC-PEEKABOO-21": "indeterminate",
    "MC-PEEKABOO-22": "partial",
    "MC-PEEKABOO-23": "suspected_noop",
}
_OUTCOMES = {
    "confirmed_change", "confirmed_no_change", "dispatched_unverified",
    "indeterminate", "partial", "suspected_noop", "refused", "read",
}


def native_result_facts(result):
    success = result.get("success") is True
    items = result.get("contentItems") or []
    text = items[0].get("text", "") if items and isinstance(items[0], dict) else ""
    code = re.search(r"\bMC-[A-Z]+-\d{2}\b", text) if not success else None
    outcome = re.search(r"\baction_outcome=([a-z_]+)", text)
    failure_code = code.group(0) if code else None
    outcome_state = outcome.group(1) if outcome and outcome.group(1) in _OUTCOMES else _FAILURE_OUTCOMES.get(failure_code)
    valid = None
    try:
        payload = json.loads(text)
        verification = payload.get("verification") if isinstance(payload, dict) else None
        if isinstance(verification, dict) and isinstance(verification.get("valid"), bool):
            valid = verification["valid"]
        if isinstance(payload, dict) and payload.get("action") == "run_project_script":
            validations = [step.get("result", {}).get("verification", {}).get("valid")
                           for step in payload.get("steps", []) if isinstance(step, dict)]
            validations = [item for item in validations if isinstance(item, bool)]
            if validations:
                valid = all(validations)
        if isinstance(payload, dict) and payload.get("action") in {
            "run_command", "read_process", "write_stdin", "stop_process"
        }:
            state, exit_code = payload.get("state"), payload.get("exit_code")
            if state == "exited" and type(exit_code) is int:
                valid = exit_code == 0
            elif state in {"signalled", "cancelled", "timed_out", "launch_failed"}:
                valid = False
    except (ValueError, TypeError, AttributeError):
        pass
    return {"native_success": success, "result_valid": valid,
            "outcome_state": outcome_state,
            "failure_reason_code": failure_code or (None if success else "native_tool_failed")}
