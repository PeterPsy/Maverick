import { useEffect, useRef, useState } from "react";
import { callMemory } from "../memoryApi";
import type { NodeDetails } from "../types";

export type NodeSection = "content" | "connections" | "sources" | "history";
type SectionResult = { node: NodeDetails; text?: string; next_cursor: string | null; has_more: boolean };

export function useNodeSections(node: NodeDetails, section: NodeSection) {
  const [details, setDetails] = useState(node);
  const [cursors, setCursors] = useState<Record<string, string | null>>({});
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const revisionRef = useRef(node.updated_at);

  useEffect(() => {
    controllerRef.current?.abort();
    revisionRef.current = node.updated_at;
    setDetails(node); setCursors({}); setLoaded({}); setError(""); setBusy(false);
    return () => controllerRef.current?.abort();
  }, [node.id, node.updated_at]);

  async function load(detail: string, more = false) {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setBusy(true); setError("");
    try {
      const result = await callMemory<SectionResult>({ action: "inspect", node_id: node.id, detail,
        ...(more ? { cursor: cursors[detail] } : {}), limit: 8, max_bytes: 16000,
      }, { signal: controller.signal });
      if (controller.signal.aborted || revisionRef.current !== node.updated_at) return;
      setDetails((current) => {
        const next = { ...current, ...result.node };
        if (detail === "content") next.body_text = (more ? current.body_text || "" : "") + (result.text || "");
        for (const key of ["claims", "sources", "revisions", "external_refs"] as const) {
          if (result.node[key]) Object.assign(next, { [key]: more ? [...(current[key] || []), ...result.node[key]] : result.node[key] });
        }
        return next;
      });
      setCursors((current) => ({ ...current, [detail]: result.next_cursor }));
      setLoaded((current) => ({ ...current, [detail]: true }));
    } catch (problem) {
      if (!controller.signal.aborted) setError(problem instanceof Error ? problem.message : "Unable to read memory section.");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }

  useEffect(() => {
    const detail = section === "sources" ? (!loaded.evidence ? "evidence" : "sources") : section;
    if (detail !== "connections" && !loaded[detail] && !busy && !error) void load(detail);
  }, [section, loaded, busy, error, node.id, node.updated_at]);

  return { details, busy, error, cursors, load, contentComplete: !!loaded.content && !cursors.content };
}
