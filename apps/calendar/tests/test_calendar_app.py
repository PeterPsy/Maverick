"""Aggregated Calendar app test suite."""

from __future__ import annotations

import unittest

from apps.calendar.tests.calendar_agent_payload_tests import CalendarAgentPayloadTest
from apps.calendar.tests.calendar_backend_api_tests import CalendarBackendApiTest
from apps.calendar.tests.calendar_conflict_tests import CalendarConflictTest
from apps.calendar.tests.calendar_contract_tests import CalendarContractTest
from apps.calendar.tests.calendar_event_model_tests import CalendarEventModelTest
from apps.calendar.tests.calendar_free_time_tests import CalendarFreeTimeTest
from apps.calendar.tests.calendar_google_oauth_tests import CalendarGoogleOAuthTest
from apps.calendar.tests.calendar_google_sync_tests import CalendarGoogleSyncTest
from apps.calendar.tests.calendar_mcp_manifest_tests import CalendarMcpManifestTest
from apps.calendar.tests.calendar_mcp_revision_tests import CalendarMcpRevisionTest
from apps.calendar.tests.calendar_reference_view_tests import CalendarReferenceViewTest


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str | None) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for case in (
        CalendarContractTest,
        CalendarBackendApiTest,
        CalendarEventModelTest,
        CalendarMcpManifestTest,
        CalendarMcpRevisionTest,
        CalendarFreeTimeTest,
        CalendarGoogleOAuthTest,
        CalendarGoogleSyncTest,
        CalendarConflictTest,
        CalendarAgentPayloadTest,
        CalendarReferenceViewTest,
    ):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite


if __name__ == "__main__":
    unittest.main()
