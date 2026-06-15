from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.runtime.output_compaction.rules import (
    RuleValidationError,
    builtin_rules,
    load_rule_payload,
    load_rules_from_directory,
)


class RuntimeOutputCompactionRulesTest(unittest.TestCase):
    def test_builtin_rules_load_from_json_in_priority_order(self) -> None:
        rules = builtin_rules()

        self.assertEqual(rules[0].rule_id, "tests/pytest_unittest")
        self.assertEqual(rules[-1].rule_id, "generic/fallback")
        self.assertTrue(all(rule.enabled for rule in rules))

    def test_unknown_top_level_rule_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuleValidationError, "unknown rule fields"):
            load_rule_payload(
                {
                    "id": "bad/rule",
                    "family": "bad",
                    "priority": 10,
                    "reducer": "generic_fallback",
                    "match": {},
                    "extra": True,
                }
            )

    def test_invalid_regex_disables_single_rule_with_diagnostic(self) -> None:
        rule = load_rule_payload(
            {
                "id": "bad/regex",
                "family": "bad",
                "priority": 10,
                "reducer": "generic_fallback",
                "match": {"text_regex_any": ["["]},
            }
        )

        self.assertFalse(rule.enabled)
        self.assertTrue(rule.diagnostics)
        self.assertEqual(rule.compiled_text_patterns(), ())

    def test_load_rules_from_directory_rejects_unknown_nested_match_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rule_path = Path(temp_dir) / "bad.json"
            rule_path.write_text(
                """
{
  "id": "bad/nested",
  "family": "bad",
  "priority": 10,
  "reducer": "generic_fallback",
  "match": {
    "text_regex_any": ["error"],
    "unknown": []
  }
}
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuleValidationError, "unknown match fields"):
                load_rules_from_directory(Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
