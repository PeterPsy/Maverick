"""Persistent domain tests for the app-owned candidate catalog."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))
from service import handle_action, mcp_result_for_tool


class CandidateCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp.name) / "data" / "videomaker-selection"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, action: str, **body):
        status, result = handle_action(self.data_root, {"action": action, **body}, workspace_id="default")
        self.assertLess(status, 400, result)
        return result

    def test_import_pipeline_activity_reference_and_restart_persist(self) -> None:
        imported = self.call(
            "import",
            candidates=[
                {
                    "id": "candidate_anna",
                    "responseNumber": 7,
                    "name": "Anna Verdi",
                    "email": "anna@example.test",
                    "city": "Roma",
                    "profileCode": "P",
                    "area": "Short form",
                    "scores": {"portfolio": 8, "budget": 7, "test": 9},
                    "reviewRank": 99,
                    "reviewed": True,
                    "decision": "da_valutare",
                },
                {
                    "id": "candidate_luca", "name": "Luca Neri", "email": "luca@example.test",
                    "scores": {"portfolio": 7, "budget": 7, "test": 7}, "reviewRank": 1,
                    "reviewed": True, "decision": "scartato"
                },
            ],
        )["import"]
        self.assertEqual(imported["created"], 2)
        self.assertTrue((self.data_root / "app.db").is_file())
        self.assertEqual(set(path.name for path in self.data_root.iterdir()), {"app.db"})

        listed = self.call("list", sort="review")["items"]
        self.assertEqual([item["id"] for item in listed], ["candidate_anna", "candidate_luca"])
        self.assertEqual([item["review_rank"] for item in listed], [99, 1], "Historical rank must not control score sorting")
        self.assertEqual(listed[0]["review_score"], 8.0)
        updated = self.call(
            "update", id="candidate_anna", payload={"decision": "selezionato", "email_status": "email_inviata", "score_test": 10}
        )["candidate"]
        self.assertEqual(updated["decision"], "selezionato")
        self.assertEqual(updated["review_score"], 8.3)
        self.assertTrue(any(event["kind"] == "pipeline" for event in updated["activities"]))

        noted = self.call("activity.add", id="candidate_anna", summary="Call fissata per lunedì")["candidate"]
        self.assertEqual(noted["activities"][0]["summary"], "Call fissata per lunedì")
        stats = self.call("stats")["stats"]
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["decision"]["selezionato"], 1)

        self.call("set_view_filter", query="Anna", decision="selezionato", email_status="email_inviata")
        state = self.call("view_filter")["view_state"]
        self.assertEqual((state["query"], state["decision"]), ("Anna", "selezionato"))
        self.assertEqual(state["email_status"], "email_inviata")
        filtered = self.call("list", apply_view_state=True)["items"]
        self.assertEqual([item["id"] for item in filtered], ["candidate_anna"])
        self.call("set_custom_view", title="Empty shortlist", refs=[])
        self.assertEqual(self.call("list", apply_view_state=True)["items"], [])

        search = self.call("references.search", query="Anna")["results"]
        self.assertEqual(search[0]["entity_id"], "candidate_anna")
        summary = self.call("references.summarize", entity_id="candidate_anna")
        self.assertNotIn("email", summary["safe_fields"])

        # A new service call opens a new SQLite connection and still sees the saved state.
        recalled = self.call("read", id="candidate_anna")["candidate"]
        self.assertEqual(recalled["email_status"], "email_inviata")
        exported = self.call("export")["export"]
        self.assertEqual(exported["schema_version"], "2")
        self.assertEqual(len(exported["candidates"]), 2)

    def test_multiple_portfolio_links_and_instagram_profiles_are_normalized(self) -> None:
        created = self.call(
            "create",
            payload={
                "name": "Link Candidate",
                "portfolioUrl": (
                    "https://canva.link/portfolio-demo e "
                    "https://www.instagram.com/reel/DEMO123/?utm_source=test / "
                    "https://www.instagram.com/link.candidate/?igsi=tracking"
                ),
                "bio": "Altri lavori su https://link-candidate.myportfolio.com/",
                "additionalInfo": "Profilo personale: instagram.com/link.personal",
                "testUrl": "https://drive.google.com/file/d/test/view",
            },
        )["candidate"]
        self.assertEqual(
            created["portfolio_links"],
            [
                "https://canva.link/portfolio-demo",
                "https://www.instagram.com/reel/DEMO123/?utm_source=test",
                "https://www.instagram.com/link.candidate/?igsi=tracking",
            ],
        )
        self.assertEqual(
            created["instagram_links"],
            ["https://www.instagram.com/link.candidate/", "https://www.instagram.com/link.personal/"],
        )
        self.assertNotIn(created["test_url"], created["portfolio_links"])

        updated = self.call("update", id=created["id"], payload={"decision": "riserva"})["candidate"]
        self.assertEqual(updated["portfolio_links"], created["portfolio_links"])
        self.assertEqual(updated["instagram_links"], created["instagram_links"])

    def test_validation_and_deduplication(self) -> None:
        self.call("create", payload={"name": "A", "email": "same@example.test"})
        status, conflict = handle_action(self.data_root, {"action": "create", "payload": {"name": "B", "email": "SAME@example.test"}}, workspace_id="default")
        self.assertEqual(status, 409)
        self.assertEqual(conflict["error"], "conflict")
        status, invalid = handle_action(self.data_root, {"action": "update", "id": "missing", "payload": {"decision": "maybe"}}, workspace_id="default")
        self.assertEqual(status, 404)
        self.assertEqual(invalid["error"], "validation_error")

    def test_dedicated_mcp_action_cannot_be_overridden(self) -> None:
        self.call("create", payload={"name": "MCP Candidate"})
        status, result = mcp_result_for_tool(self.data_root, "videomaker_selection_candidate_stats", {"action": "delete"}, workspace_id="default")
        self.assertEqual(status, 200)
        self.assertEqual(result["stats"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
