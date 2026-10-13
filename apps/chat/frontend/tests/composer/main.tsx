import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ChatComposer } from "../../src/components/ChatComposer";
import type { AppReference } from "../../src/api/client";
import { listenForShellReferenceDrops } from "../../src/lib/shellReferenceDrop";
import { useComposerAttachments } from "../../src/hooks/useComposerAttachments";
import { fixtureUsage } from "./usage";
import "../../src/styles/main.css";
import "../../src/widgets/chat-floating/styles.css";

const params = new URLSearchParams(location.search);
const width = Number(params.get("width") || 390);
const widget = params.get("widget") === "true";
const count = Number(params.get("count") || 1);
const research = params.get("research") === "true";
if (params.has('shell_origin')) Object.defineProperty(window, '__MAVERICK_PLATFORM_ORIGIN__', { value: params.get('shell_origin') });
listenForShellReferenceDrops();

function ComposerFixture() {
  const { attachments, addAttachments, removeAttachment } = useComposerAttachments();
  const [value, setValue] = useState("");
  const [references, setReferences] = useState<AppReference[]>([]);
  const [sent, setSent] = useState(0);
  const [stopped, setStopped] = useState(0);
  const [multiAgentMode, setMultiAgentMode] = useState<"off" | "auto" | "multi" | "group_chat">("off");
  return (
    <div className={widget ? "chatapp-root chat-floating-widget-shell__body" : "chatapp-root"} style={{ width, display: "flex", alignItems: "center" }}>
      <div style={{ width: "100%" }}>
        <ChatComposer
          activeProviderId="codex"
          agents={[{ id: "reviewer", name: "Reviewer", description: "Review work", skill_ids: [], enabled: true }]}
          attachments={attachments}
          canStopTurn
          disabled={false}
          error={null}
          executionMode="sandbox"
          isSending={false}
          mentionItems={[{ id: "storage", label: "Storage", description: "Workspace files", kind: "app" }]}
          multiAgentMode={multiAgentMode}
          onAddAttachments={addAttachments}
          onChange={setValue}
          onReferenceAdd={(reference) => setReferences((current) => [...current, reference])}
          onSelectAgent={() => undefined}
          onSelectMultiAgentMode={setMultiAgentMode}
          onSelectProvider={() => undefined}
          onRemoveAttachment={removeAttachment}
          onStopTurn={() => setStopped((current) => current + 1)}
          onSubmit={() => { setSent((current) => current + 1); setValue(""); }}
          providers={[{ provider_id: "codex", label: "Codex", description: "", status: "active", default_model_family: null }]}
          queuedCount={0}
          queuedPreview={null}
          selectedAgentTypeId={research ? "__research__" : ""}
          isolatedResearch={research}
          researchAvailable={research}
          value={value}
          usage={params.has("usage") ? fixtureUsage : null}
        />
        <output data-testid="sent">{sent}</output>
        <output data-testid="stopped">{stopped}</output>
        <output data-testid="references">{JSON.stringify(references)}</output>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <main style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, height: "100dvh" }}>
    <button data-testid="outside" style={{ position: "absolute", bottom: 8, left: 8 }} type="button">Outside composer</button>
    {Array.from({ length: count }, (_, index) => <ComposerFixture key={index} />)}
  </main>,
);
