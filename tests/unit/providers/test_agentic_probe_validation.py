"""Live probes must account for every response, not just aggregate counters."""

import unittest

from core.providers.agentic_protocol import (
    AgenticModelEvent, AgenticProviderPrivateState, AgenticToolCall, AgenticUsage,
)
from core.providers.agentic_probe_validation import validate_probe_response


def response(*, final=False):
    outcome = AgenticModelEvent("text_final", "request", 1, text="OK") if final else (
        AgenticModelEvent("tool_call", "request", 1,
                          tool_call=AgenticToolCall("call", "list", {}))
    )
    return [
        outcome,
        AgenticModelEvent("provider_state", "request", 2,
                          provider_private_state=AgenticProviderPrivateState(
                              "codec", "1", "1", "application/json", b"{}")),
        AgenticModelEvent("usage", "request", 3, usage=AgenticUsage(1, 1, 1)),
        AgenticModelEvent("completed", "request", 4),
    ]


class AgenticProbeValidationTest(unittest.TestCase):
    def test_complete_tool_and_final_responses_pass(self):
        for final in (False, True):
            self.assertTrue(validate_probe_response(response(final=final), final=final))

    def test_each_response_requires_its_own_usage_state_and_completion(self):
        for final in (False, True):
            for kind in ("usage", "provider_state", "completed"):
                with self.subTest(final=final, kind=kind):
                    events = [e for e in response(final=final) if e.event_type != kind]
                    self.assertFalse(validate_probe_response(events, final=final))

    def test_parallel_or_final_tool_calls_never_pass(self):
        for final in (False, True):
            events = response(final=final)
            events.insert(1, AgenticModelEvent("tool_call", "request", 2,
                          tool_call=AgenticToolCall("other", "list", {})))
            self.assertFalse(validate_probe_response(events, final=final))

    def test_blank_final_duplicate_terminal_and_late_error_fail(self):
        for text in (None, "", " \n\t"):
            events = response(final=True)
            events[0] = AgenticModelEvent("text_final", "request", 1, text=text)
            self.assertFalse(validate_probe_response(events, final=True))
        for extra in (AgenticModelEvent("completed", "request", 5),
                      AgenticModelEvent("error", "request", 5, error_code="provider_unavailable")):
            self.assertFalse(validate_probe_response([*response(final=True), extra], final=True))

    def test_missing_payload_and_cross_request_events_fail(self):
        for kind in ("tool_call", "usage", "provider_state"):
            events = response()
            index = next(i for i, e in enumerate(events) if e.event_type == kind)
            events[index] = AgenticModelEvent(kind, "request", index + 1)
            self.assertFalse(validate_probe_response(events, final=False))
        events = response(final=True)
        events[-1] = AgenticModelEvent("completed", "other-request", 4)
        self.assertFalse(validate_probe_response(events, final=True))


if __name__ == "__main__":
    unittest.main()
