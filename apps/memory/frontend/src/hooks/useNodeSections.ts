import { useEffect, useRef, useState } from "react";
import { callMemory } from "../memoryApi";
import type { NodeDetails } from "../types";

export type NodeSection = "content" | "connections" | "sources" | "history";
type SectionResult = { node: NodeDetails; text?: string; next_cursor: string | null; has_more: boolean };

export function useNodeSections(node: NodeDetails, section: NodeSection) {
  const revision = `${node.id}:${node.state_revision || node.updated_at}`;
  const [details, setDetails] = useState(node);
  const [cursors, setCursors] = useState<Record<string, string | null>>({});
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const revisionRef = useRef(revision);

  useEffect(() => {
    controllerRef.current?.abort();
    revisionRef.current = revision;
    setDetails(node); setCursors({}); setLoaded({}); setError(""); setBusy(false);
    return () => controllerRef.current?.abort();
  }, [revision]);

  async function load(detail: string, more = false) {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setBusy(true); setError("");
    try {
      const result = await callMemory<SectionResult>({ action: "inspect", node_id: node.id, detail,
        ...(more ? { cursor: cursors[detail] } : {}), limit: 8, max_bytes: 16000,
      }, { signal: controller.signal });
      if (controller.signal.aborted || revisionRef.current !== revision) return;
      const changedState = !!result.node.state_revision && result.node.state_revision !== details.state_revision;
      setDetails((current) => {
        const sameState = current.state_revision === result.node.state_revision;
        const next = sameState ? { ...current, ...result.node } : { ...result.node };
        if (sameState && current.state_observation === "live" && result.node.state_observation !== "live") {
          for (const key of ["state_observation", "freshness", "source_state", "verification"] as const) next[key] = current[key];
        }
        if (detail === "content") next.body_text = (more ? current.body_text || "" : "") + (result.text || "");
        for (const key of ["claims", "sources", "revisions", "external_refs"] as const) {
          if (result.node[key]) Object.assign(next, { [key]: more ? [...(current[key] || []), ...result.node[key]] : result.node[key] });
        }
        return next;
      });
      setCursors((current) => ({ ...(changedState ? {} : current), [detail]: result.next_cursor }));
      setLoaded((current) => ({ ...(changedState ? {} : current), [detail]: true }));
    } catch (problem) {
      if (!controller.signal.aborted) setError(problem instanceof Error ? problem.message : "Unable to read memory section.");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }

  useEffect(() => {
    const detail = section === "sources" ? (!loaded.evidence ? "evidence" : "sources") : section;
    if (detail !== "connections" && !loaded[detail] && !busy && !error) void load(detail);
  }, [section, loaded, busy, error, revision]);

  return { details, busy, error, cursors, load, contentComplete: !!loaded.content && !cursors.content };
}
