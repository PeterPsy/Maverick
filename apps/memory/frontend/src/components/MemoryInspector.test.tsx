import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FloatingNodePanel } from "./FloatingNodePanel";
import { MemoryManagement } from "./MemoryManagement";
import type { NodeDetails } from "../types";

describe("Memory inspector", () => {
  it("allows restoring and removing an excluded memory and disables active-only actions", () => {
    const markup = renderToStaticMarkup(<MemoryManagement node={{
      id: "excluded", title: "Preference", type: "fact", status: "excluded", updated_at: "revision-2",
      duplicate_candidates: [{ id: "target", title: "Other preference", updated_at: "target-revision" }],
    }} onSelect={() => {}} onClose={() => {}} />);
    for (const action of ["Correct fact", "Verify evidence", "Find", "Merge into Other preference"]) {
      expect(markup).toMatch(new RegExp(`<button[^>]*disabled=""[^>]*>${action}</button>`));
    }
    for (const action of ["Include in retrieval", "Remove memory"]) {
      expect(markup).toContain(`<button type="button">${action}</button>`);
    }
  });
  it("separates source currency, compilation and contradictory evidence with correction actions", () => {
    const node: NodeDetails = {
      id: "node-1", title: "Renewal", type: "fact", updated_at: "2026-10-11", confidence: 0,
      compiled_page: { id: "page-1", node_id: "node-1", title: "Renewal", freshness: "fresh", compilation_state: "fresh", source_state: "current", verification: "conflict" },
      claims: [{ id: "claim-1", wiki_page_id: "page-1", node_id: "node-1", claim_text: "The renewal costs 1200 euro.", verification: "conflict",
        contradictions: [{ id: "cite-1", claim_id: "claim-1", quote: "The renewal costs 9000 euro.", source_chunk_id: "chunk-1" }],
        related_evidence: [{ id: "cite-2", claim_id: "claim-1", quote: "The monthly renewal costs 1200 euro.", evidence_relation: "related" }] }],
    };
    const markup = renderToStaticMarkup(<FloatingNodePanel node={node} relationships={[]} onClose={() => {}} onSelect={() => {}} />);
    expect(markup).toContain("Source: current");
    expect(markup).toContain("Evidence: conflict");
    expect(markup).toContain("Contradicting passage");
    expect(markup).toContain("Relevant passage · needs review");
    expect(markup).toContain("9000 euro");
    expect(markup).toContain("Correct fact");
    expect(markup).toContain("Exclude from retrieval");
    expect(markup).toContain("Merge into another memory");
    expect(markup).toContain("0%");
  });
});
