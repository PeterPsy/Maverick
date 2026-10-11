// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { callMemory } from "../memoryApi";
import type { NodeDetails } from "../types";
import { useNodeSections } from "./useNodeSections";

vi.mock("../memoryApi", () => ({ callMemory: vi.fn() }));
const call = vi.mocked(callMemory);
const card: NodeDetails = {
  id: "contract", title: "Annual contract", type: "fact", updated_at: "unchanged-fact",
  state_revision: "evidence-1", state_observation: "indexed", verification: "verified",
  freshness: "fresh", source_state: "current",
};

function Inspector({ node }: { node: NodeDetails }) {
  const { details } = useNodeSections(node, "sources");
  return <div>{details.verification} / {details.source_state}
    {(details.claims || []).flatMap((claim) => [...(claim.citations || []), ...(claim.contradictions || [])]).map((cite) => <p key={cite.id}>{cite.quote}</p>)}
  </div>;
}

describe("selective inspector lifecycle", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    call.mockReset();
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });
  async function render(node: NodeDetails) {
    await act(async () => root.render(<Inspector node={node} />));
  }

  it("reloads evidence after a source edit even when the fact timestamp is unchanged", async () => {
    let current = card;
    call.mockImplementation(async (request) => ({ node: {
      ...current,
      ...(request.detail === "evidence" ? { state_observation: "live", claims: [{
        id: "claim", wiki_page_id: "page", node_id: card.id, claim_text: "Annual cost",
        ...(current.state_revision === "evidence-1"
          ? { citations: [{ id: "old", claim_id: "claim", quote: "1200 euro" }] }
          : { contradictions: [{ id: "new", claim_id: "claim", quote: "9000 euro" }] }),
      }] } : { sources: [] }),
    }, has_more: false, next_cursor: null }));
    await render(card);
    expect(container.textContent).toContain("verified");
    expect(container.textContent).toContain("1200 euro");
    current = { ...card, state_revision: "evidence-2", verification: "conflict" };
    await render(current);
    expect(container.textContent).toContain("conflict");
    expect(container.textContent).toContain("9000 euro");
    expect(container.textContent).not.toContain("1200 euro");
    expect(call.mock.calls.filter(([request]) => request.detail === "evidence")).toHaveLength(2);
  });

  it("retains live stale evidence when the source list supplies indexed indicators", async () => {
    call.mockImplementation(async (request) => ({ node: request.detail === "evidence" ? {
      ...card, state_observation: "live", freshness: "stale", verification: "unverified", source_state: "stale", claims: [],
    } : { ...card, sources: [] }, has_more: false, next_cursor: null }));
    await render(card);
    expect(call.mock.calls.map(([request]) => request.detail)).toEqual(["evidence", "sources"]);
    expect(container.textContent).toContain("unverified / stale");
  });

  it("ignores an older in-flight evidence response after the observed state changes", async () => {
    let resolveOld: (value: unknown) => void = () => {};
    const pending = new Promise((resolve) => { resolveOld = resolve; });
    call.mockImplementation(async (request) => request.detail === "evidence" ? pending : {
      node: card, has_more: false, next_cursor: null,
    });
    await render(card);
    const next = { ...card, state_revision: "evidence-2", verification: "conflict" };
    call.mockImplementation(async (request) => ({ node: {
      ...next,
      ...(request.detail === "evidence" ? { state_observation: "live", claims: [{
        id: "claim", wiki_page_id: "page", node_id: card.id, claim_text: "Annual cost",
        contradictions: [{ id: "new", claim_id: "claim", quote: "9000 euro" }],
      }] } : { sources: [] }),
    }, has_more: false, next_cursor: null }));
    await render(next);
    expect(call.mock.calls.filter(([request]) => request.detail === "evidence")).toHaveLength(2);
    await act(async () => resolveOld({ node: { ...card, state_observation: "live", claims: [{
      id: "claim", wiki_page_id: "page", node_id: card.id, claim_text: "Annual cost",
      citations: [{ id: "old", claim_id: "claim", quote: "1200 euro" }],
    }] }, has_more: false, next_cursor: null }));
    expect(container.textContent).toContain("conflict");
    expect(container.textContent).toContain("9000 euro");
    expect(container.textContent).not.toContain("1200 euro");
  });
});
