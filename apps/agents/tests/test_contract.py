from __future__ import annotations

import json
from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]


class AgentsContractTest(unittest.TestCase):
    def test_contract_declares_one_agent_record_store(self) -> None:
        contract = json.loads((APP_ROOT / "app_contract.json").read_text(encoding="utf-8"))

        self.assertEqual(
            contract["storage"]["primary_paths"],
            ["data/agents/agents.json", "data/agents/view_state.json"],
        )
        self.assertEqual(contract["storage"]["data_schema_version"], "2")
        self.assertEqual(
            contract["capabilities"]["view_surfaces"][0]["entity_types"],
            ["agent_type"],
        )
        self.assertEqual(
            [item["interface"] for item in contract["provides"]],
            ["agent.catalog"],
        )


if __name__ == "__main__":
    unittest.main()
