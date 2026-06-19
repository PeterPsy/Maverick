"""Tests for semantic JSON provider-history compaction."""

from __future__ import annotations

import json
import unittest

from core.runtime.output_compaction.models import ToolOutputCompactionPolicy
from core.runtime.output_compaction.provider_hooks import build_codex_post_tool_use_response


class ProviderHookSemanticJsonCompactionTest(unittest.TestCase):
    def test_codex_post_tool_use_preserves_semantic_memory_context_json(self) -> None:
        items = []
        for index in range(8):
            node_id = f"node_prompt_review_{index}"
            body_text = (
                f"Preferenza prompt review iOS Maverick item {index}: preserve semantic detail. "
                + ("Verbose body filler. " * 600)
            )
            items.append(
                {
                    "kind": "memory_node",
                    "id": node_id,
                    "node_id": node_id,
                    "type": "fact",
                    "title": f"Preferenza prompt review iOS Maverick {index}",
                    "summary": f"Prompt review preference summary {index}.",
                    "body_text": body_text,
                    "node": {
                        "id": node_id,
                        "node_id": node_id,
                        "type": "fact",
                        "title": f"Preferenza prompt review iOS Maverick {index}",
                        "summary": f"Prompt review preference summary {index}.",
                        "body_text": body_text,
                    },
                    "entity": {"entity_type": "node", "entity_id": node_id},
                    "locator": {"kind": "memory_node", "value": node_id},
                    "match_sources": ["node"],
                    "relevance": round(1.0 - (index * 0.05), 3),
                    "compiled": {
                        "wiki_page_id": f"wiki_{index}",
                        "summary": f"Compiled prompt preference summary {index}.",
                        "body_markdown": "# Full compiled markdown\n\n" + ("compiled markdown filler\n" * 700),
                        "freshness": "fresh",
                        "citations": [
                            {
                                "source_chunk_id": f"chunk_{index}",
                                "quote": "Prompt review evidence quote. " * 20,
                            }
                        ],
                    },
                    "storage_references": [
                        {
                            "stable_storage_file_id": f"file_prompt_{index}",
                            "deep_link": f"/app/storage/files/file_prompt_{index}",
                        }
                    ],
                }
            )
        memory_json = json.dumps(
            {
                "status_code": 200,
                "query": "Preferenza prompt review iOS Maverick",
                "items": items,
            }
        )

        response = build_codex_post_tool_use_response(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "maverick app memory cli run memory --action context "
                        "--query 'Preferenza prompt review iOS Maverick' --limit 8 --json"
                    )
                },
                "tool_response": {"stdout": memory_json, "stderr": "", "exit_code": 0},
            },
            runtime_session_id="sess-1",
            policy=ToolOutputCompactionPolicy(
                min_original_bytes=1000,
                success_min_savings_ratio=0.20,
                target_max_compacted_bytes=10_000,
            ),
        )

        self.assertTrue(response["emit"])
        reason = response["response"]["reason"]
        self.assertIn("[tool output compacted]", reason)
        self.assertIn("semantic json payload", reason)
        self.assertIn("Preferenza prompt review iOS Maverick 4", reason)
        self.assertIn("node_prompt_review_4", reason)
        self.assertIn("body_text_char_count", reason)
        self.assertIn("body_markdown_char_count", reason)
        self.assertNotIn("compiled markdown filler", reason)
        self.assertEqual(response["output_compaction"]["rule_id"], "data/json_large")
        self.assertEqual(response["output_compaction"]["facts"]["semantic_items"], 8)


if __name__ == "__main__":
    unittest.main()
