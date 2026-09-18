import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import type { AgentTypeSummary, AppReference, ChatUsageSummary, ProviderItem } from "../api/client";
import type { MultiAgentComposerMode } from "../api/client";
import type { ComposerAttachment } from "../lib/attachments";
import type { DeviceUseMode, DeviceUsePermission, NativeDeviceUseSnapshot } from "../lib/deviceUse";
import { hasInvalidAttachments } from "../lib/attachments";
import { isGroupChatComposerModeEnabled } from "../lib/interAgentFeatures";
import type { MentionItem } from "../lib/mentions";
import { isResearchRunner, RESEARCH_RUNNER_ID } from "../lib/runtimeProfiles";
import { useComposerEditor } from "../hooks/useComposerEditor";
import { useMentionPicker } from "../hooks/useMentionPicker";
import { AgentSelector } from "./AgentSelector";
import { AttachmentMenu } from "./AttachmentMenu";
import { AttachmentPreviewStrip } from "./AttachmentPreviewStrip";
import { ComposerActions } from "./ComposerActions";
import { ComposerDictationButton } from "./ComposerDictationButton";
import { ComposerRuntimeBadges } from "./ComposerRuntimeBadges";
import { ComposerUtilities } from "./ComposerUtilities";
import { DeviceUseControl } from "./DeviceUseControl";
import { MentionPanel } from "./MentionPanel";
import { QueuedMessageNotice } from "./QueuedMessageNotice";

export type ExecutionMode = "sandbox" | "full-access";

export type ChatComposerProps = {
  activeProviderId: string;
  agentCatalogLoading?: boolean;
  agentSelectorLocked?: boolean;
  agents: AgentTypeSummary[];
  attachments: ComposerAttachment[];
  canStopTurn: boolean;
  disabled: boolean;
  deviceUseAvailable?: boolean;
  deviceUseBusy?: boolean;
  deviceUseEnabled?: boolean;
  deviceUseLocked?: boolean;
  deviceUseMode?: DeviceUseMode;
  deviceUseSnapshot?: NativeDeviceUseSnapshot;
  error: string | null;
  executionMode: ExecutionMode | null;
  isEmptyMode?: boolean;
  isSending: boolean;
  isolatedResearch?: boolean;
  mentionItems: MentionItem[];
  multiAgentBudgetLabel?: string;
  multiAgentGroupChatEnabled?: boolean;
  multiAgentMode?: MultiAgentComposerMode;
  onAddAttachments: (files: File[]) => void;
  onCapturePageArea?: () => void;
  onChange: (value: string) => void;
  onReferenceAdd?: (reference: AppReference) => void;
  onReferenceRemove?: (reference: AppReference) => void;
  onSearchReferences?: (query: string, signal: AbortSignal) => Promise<MentionItem[]>;
  onSelectMultiAgentMode?: (mode: MultiAgentComposerMode) => void;
  onSelectAgent: (agentTypeId: string) => void;
  onSelectProvider: (providerId: string, reasoningEffort?: string) => void;
  onReasoningEffortChange?: (effort: string) => void;
  providerSelectorLocked?: boolean;
  onRemoveAttachment: (attachmentId: string) => void;
  onStopTurn: () => void;
  onSubmit: () => void;
  onConfigureDeviceUse?: (settings: NativeDeviceUseSnapshot["settings"]) => Promise<void>;
  onRefreshDeviceUse?: () => Promise<NativeDeviceUseSnapshot>;
  onRequestDeviceUsePermission?: (permission: DeviceUsePermission) => void;
  onSelectDeviceUseMode?: (mode: DeviceUseMode) => void;
  providers: ProviderItem[];
  reasoningEffort?: string;
  researchAvailable?: boolean;
  queuedCount: number;
  queuedPreview: string | null;
  selectedAgentTypeId: string;
  transcriptionProviderAppId?: string;
  transcriptionProviderAvailable?: boolean;
  transcriptionChunkedDictationSupported?: boolean;
  transcriptionMaxAudioBytes?: number;
  transcriptionMaxDurationSeconds?: number;
  transcriptionContentTypes?: string[];
  usage?: ChatUsageSummary | null;
  value: string;
};

export function ChatComposer({
  activeProviderId,
  agentCatalogLoading = false,
  agentSelectorLocked = false,
  agents,
  attachments,
  canStopTurn,
  disabled,
  deviceUseAvailable = false,
  deviceUseBusy = false,
  deviceUseEnabled = false,
  deviceUseLocked = false,
  deviceUseMode = "off",
  deviceUseSnapshot,
  error,
  executionMode,
  isEmptyMode = false,
  isSending,
  isolatedResearch = false,
  mentionItems,
  multiAgentBudgetLabel = "",
  multiAgentGroupChatEnabled = isGroupChatComposerModeEnabled(),
  multiAgentMode = "off",
  onAddAttachments,
  onCapturePageArea,
  onChange,
  onReferenceAdd,
  onReferenceRemove,
  onSearchReferences,
  onSelectMultiAgentMode,
  onSelectAgent,
  onSelectProvider,
  onReasoningEffortChange = () => undefined,
  providerSelectorLocked = false,
  onRemoveAttachment,
  onStopTurn,
  onSubmit,
  onConfigureDeviceUse,
  onRefreshDeviceUse,
  onRequestDeviceUsePermission,
  onSelectDeviceUseMode,
  providers,
  reasoningEffort = "",
  researchAvailable = false,
  queuedCount,
  queuedPreview,
  selectedAgentTypeId,
  transcriptionProviderAppId = "",
  transcriptionProviderAvailable = false,
  transcriptionChunkedDictationSupported = false,
  transcriptionMaxAudioBytes = 0,
  transcriptionMaxDurationSeconds = 0,
  transcriptionContentTypes = [],
  usage = null,
  value,
}: ChatComposerProps) {
  const researchEnabled = isResearchRunner(selectedAgentTypeId);
  const [caretIndex, setCaretIndex] = useState(value.length);
  const [multiAgentMenuOpen, setMultiAgentMenuOpen] = useState(false);
  const editorRef = useRef<HTMLDivElement | null>(null);
  const pendingCaretIndexRef = useRef<number | null>(null);
  const {
    activeSkillMention,
    appMentionPickerQuery,
    appPickerButtonRef,
    appPickerItems,
    appPickerPanelRef,
    appPickerSearchError,
    appPickerSearchPending,
    appPickerSearchRef,
    clearDismissedMention,
    dismissSkillMention,
    filteredMentionItems,
    handleAppMentionPickerKey,
    insertAppMentions,
    insertMention,
    isAppMentionPickerOpen,
    mentionTokens,
    openAppPicker,
    removeMention,
    selectAppMentionPickerItem,
    selectedAppIndex,
    selectedMentionIndex,
    setSelectedMentionIndex,
    updateActiveAppMentionQuery,
  } = useMentionPicker({
    caretIndex,
    editorRef,
    mentionItems,
    onChange,
    onReferenceAdd,
    onReferenceRemove,
    onSearchReferences,
    pendingCaretIndexRef,
    setCaretIndex,
    value,
  });
  const {
    dictationError,
    insertDictationTranscript,
    onComposerKeyDown,
    onDragOver,
    onDrop,
    onPaste,
    setDictationError,
    syncCaret,
    updateComposerFromEditor,
  } = useComposerEditor({
    caretIndex,
    clearDismissedMention,
    disabled,
    editorRef,
    filteredMentionItems,
    handleAppMentionPickerKey,
    insertAppMentions,
    insertMention,
    isSkillMentionPanelOpen: Boolean(activeSkillMention),
    mentionTokens,
    onAddAttachments,
    onChange,
    onRemoveMention: removeMention,
    onSubmit,
    pendingCaretIndexRef,
    selectedMentionIndex,
    setCaretIndex,
    setDismissedSkillMention: () => dismissSkillMention(activeSkillMention),
    setSelectedMentionIndex,
    value,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  function onAppPickerSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) {
      return;
    }
    if (handleAppMentionPickerKey(event, true)) {
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
    }
  }

  return (
    <>
      <section className={`chat-ui-surface chatapp-composer ${isEmptyMode ? "is-empty-mode" : "is-docked"}`}>
        <form className="chatapp-form-stack" onSubmit={submit}>
          <AttachmentPreviewStrip attachments={attachments} disabled={isSending} onRemoveAttachment={onRemoveAttachment} />
          <QueuedMessageNotice queuedCount={queuedCount} queuedPreview={queuedPreview} />
          <div className={`chatapp-composer__input-shell ${isAppMentionPickerOpen ? "has-app-picker" : ""}`}>
            {isAppMentionPickerOpen ? (
              <MentionPanel
                activeIndex={Math.min(selectedAppIndex, Math.max(appPickerItems.length - 1, 0))}
                className="chatapp-mention-panel--app-picker"
                items={appPickerItems}
                kind="app"
                onSelect={selectAppMentionPickerItem}
                onSearchKeyDown={onAppPickerSearchKeyDown}
                onSearchQueryChange={updateActiveAppMentionQuery}
                query={appMentionPickerQuery}
                searchInputRef={appPickerSearchRef}
                searchPlaceholder="Search apps and references"
                searchQuery={appMentionPickerQuery}
                showHeader={false}
                showSearchLabel={false}
                isLoading={appPickerSearchPending}
                statusMessage={appPickerSearchError}
                ref={appPickerPanelRef}
              />
            ) : null}
            <div className={`chatapp-composer__text-area ${isSending ? "is-busy" : "is-idle"}`}>
              <div
                aria-disabled={disabled}
                aria-multiline="true"
                className={`chat-ui-input chat-ui-input--textarea chatapp-composer__field chatapp-composer__editor ${value ? "" : "is-empty"}`}
                contentEditable={!disabled}
                data-placeholder="Message Maverick..."
                onClick={(event) => syncCaret(event.currentTarget)}
                onDragOver={onDragOver}
                onDrop={onDrop}
                onInput={(event) => updateComposerFromEditor(event.currentTarget)}
                onKeyDown={onComposerKeyDown}
                onKeyUp={(event) => syncCaret(event.currentTarget)}
                onMouseUp={(event) => syncCaret(event.currentTarget)}
                onPaste={onPaste}
                ref={editorRef}
                role="textbox"
                suppressContentEditableWarning
                tabIndex={disabled ? -1 : 0}
              />
              {activeSkillMention ? (
                <MentionPanel
                  activeIndex={Math.min(selectedMentionIndex, Math.max(filteredMentionItems.length - 1, 0))}
                  items={filteredMentionItems}
                  kind={activeSkillMention.kind}
                  onSelect={insertMention}
                  query={activeSkillMention.query}
                />
              ) : null}
            </div>
            <div className="chatapp-composer__toolbar">
              <div className="chatapp-composer__tools">
                {!isolatedResearch ? (
                  <AttachmentMenu
                    attachments={attachments}
                    disabled={disabled || deviceUseEnabled}
                    onAddAttachments={onAddAttachments}
                    onCapturePageArea={onCapturePageArea}
                  />
                ) : null}
                {!isolatedResearch && deviceUseAvailable && deviceUseSnapshot
                    && onConfigureDeviceUse && onRefreshDeviceUse
                    && onRequestDeviceUsePermission && onSelectDeviceUseMode ? (
                  <DeviceUseControl
                    busy={deviceUseBusy}
                    locked={deviceUseLocked}
                    mode={deviceUseMode}
                    onConfigure={onConfigureDeviceUse}
                    onModeChange={onSelectDeviceUseMode}
                    onRefresh={onRefreshDeviceUse}
                    onRequestPermission={onRequestDeviceUsePermission}
                    snapshot={deviceUseSnapshot}
                  />
                ) : null}
                <ComposerUtilities>
                  {!isolatedResearch && onCapturePageArea ? (
                    <button
                      aria-label="Capture page area"
                      className="chatapp-composer__tool-button chatapp-composer-utilities__capture-button"
                      disabled={disabled || deviceUseEnabled}
                      onClick={onCapturePageArea}
                      title="Capture page area"
                      type="button"
                    >
                      <span aria-hidden="true" className="material-symbols-rounded">
                        crop_free
                      </span>
                    </button>
                  ) : null}
                  {!isolatedResearch ? (
                    <button
                      aria-expanded={isAppMentionPickerOpen}
                      aria-haspopup="listbox"
                      aria-label="Apps and references"
                      className={`chatapp-composer__tool-button ${isAppMentionPickerOpen ? "is-active" : ""}`}
                      disabled={disabled || deviceUseEnabled}
                      onClick={openAppPicker}
                      ref={appPickerButtonRef}
                      type="button"
                    >
                      <span aria-hidden="true" className="material-symbols-rounded">
                        apps
                      </span>
                    </button>
                  ) : null}
                  {!isolatedResearch ? (
                    <MultiAgentModeControl
                      budgetLabel={multiAgentBudgetLabel}
                      disabled={disabled || isSending || deviceUseEnabled}
                      groupChatEnabled={multiAgentGroupChatEnabled}
                      menuOpen={multiAgentMenuOpen}
                      mode={multiAgentMode}
                      onMenuOpenChange={setMultiAgentMenuOpen}
                      onSelect={(nextMode) => {
                        onSelectMultiAgentMode?.(nextMode);
                        setMultiAgentMenuOpen(false);
                      }}
                    />
                  ) : null}
                  {researchAvailable || researchEnabled ? (
                    <button
                      aria-label={researchEnabled ? "Disable Research" : "Enable Research"}
                      aria-pressed={researchEnabled}
                      className={`chatapp-composer__tool-button chatapp-research-control ${researchEnabled ? "is-active" : ""}`}
                      disabled={disabled || isSending || deviceUseEnabled || agentSelectorLocked}
                      onClick={() => {
                        onSelectAgent(researchEnabled ? "" : RESEARCH_RUNNER_ID);
                      }}
                      title={researchEnabled ? "Disable isolated web research" : "Enable isolated web research"}
                      type="button"
                    >
                      <span aria-hidden="true" className="material-symbols-rounded">
                        travel_explore
                      </span>
                      {researchEnabled ? <span className="chatapp-research-control__label">Research</span> : null}
                    </button>
                  ) : null}
                  {!researchEnabled ? (
                    <AgentSelector
                      agents={agents}
                      disabled={disabled || isSending || deviceUseEnabled}
                      loading={agentCatalogLoading}
                      locked={agentSelectorLocked}
                      onSelect={onSelectAgent}
                      selectedAgentTypeId={selectedAgentTypeId}
                    />
                  ) : null}
                  <ComposerRuntimeBadges
                    activeProviderId={activeProviderId}
                    disabled={disabled || isSending || deviceUseEnabled}
                    executionMode={executionMode}
                    locked={providerSelectorLocked}
                    onSelectProvider={onSelectProvider}
                    onReasoningEffortChange={onReasoningEffortChange}
                    providers={providers}
                    reasoningEffort={reasoningEffort}
                    usage={usage}
                  />
                </ComposerUtilities>
              </div>
              <ComposerActions
                canSend={!disabled && !hasInvalidAttachments(attachments) && Boolean(value.trim() || attachments.length)}
                canStopTurn={canStopTurn}
                dictationControl={
                  <ComposerDictationButton
                    chunkedDictationSupported={transcriptionChunkedDictationSupported}
                    disabled={disabled || isSending || deviceUseEnabled}
                    maxAudioBytes={transcriptionMaxAudioBytes}
                    maxDurationSeconds={transcriptionMaxDurationSeconds}
                    onError={setDictationError}
                    onTranscript={insertDictationTranscript}
                    providerAppId={transcriptionProviderAppId}
                    providerAvailable={transcriptionProviderAvailable}
                    supportedContentTypes={transcriptionContentTypes}
                  />
                }
                onStopTurn={onStopTurn}
                onSubmit={onSubmit}
              />
            </div>
          </div>
          {dictationError || error ? (
            <div className="chat-ui-field__message chat-ui-field__message--error chatapp-composer__error">{dictationError || error}</div>
          ) : null}
        </form>
      </section>
    </>
  );
}

function MultiAgentModeControl({
  budgetLabel,
  disabled,
  groupChatEnabled,
  menuOpen,
  mode,
  onMenuOpenChange,
  onSelect,
}: {
  budgetLabel: string;
  disabled: boolean;
  groupChatEnabled: boolean;
  menuOpen: boolean;
  mode: MultiAgentComposerMode;
  onMenuOpenChange: (open: boolean) => void;
  onSelect: (mode: MultiAgentComposerMode) => void;
}) {
  const label = multiAgentModeLabel(mode);
  const modeItems: MultiAgentComposerMode[] = groupChatEnabled ? ["off", "auto", "multi", "group_chat"] : ["off", "auto", "multi"];
  const controlRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!menuOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (!target || controlRef.current?.contains(target)) {
        return;
      }
      onMenuOpenChange(false);
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }
      onMenuOpenChange(false);
      triggerRef.current?.focus();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen, onMenuOpenChange]);

  return (
    <div className="chatapp-multi-agent-control" ref={controlRef}>
      <button
        aria-expanded={menuOpen}
        aria-haspopup="menu"
        aria-label={`Multi-agent mode: ${label}`}
        className={`chatapp-composer__tool-button chatapp-multi-agent-control__button ${mode !== "off" ? "is-active" : ""}`}
        disabled={disabled}
        onClick={() => onMenuOpenChange(!menuOpen)}
        ref={triggerRef}
        title="Multi-agent mode"
        type="button"
      >
        <span aria-hidden="true" className="material-symbols-rounded">
          account_tree
        </span>
        <span className="chatapp-multi-agent-control__label">{label}</span>
      </button>
      {menuOpen ? (
        <div className="chatapp-multi-agent-menu" role="menu">
          {modeItems.map((item) => (
            <button
              aria-checked={mode === item}
              className="chatapp-multi-agent-menu__item"
              key={item}
              onClick={() => onSelect(item)}
              role="menuitemradio"
              type="button"
            >
              <span aria-hidden="true" className="material-symbols-rounded">
                {mode === item ? "radio_button_checked" : "radio_button_unchecked"}
              </span>
              <span>{multiAgentModeLabel(item)}</span>
            </button>
          ))}
          {budgetLabel ? <div className="chatapp-multi-agent-menu__budget">{budgetLabel}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function multiAgentModeLabel(mode: MultiAgentComposerMode): string {
  if (mode === "auto") {
    return "Auto";
  }
  if (mode === "multi") {
    return "Multi";
  }
  if (mode === "group_chat") {
    return "Group chat";
  }
  return "Off";
}
