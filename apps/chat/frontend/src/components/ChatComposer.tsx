import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import type { AgentTypeSummary, AppReference, ChatUsageSummary, ProviderItem } from "../api/client";
import type { MultiAgentComposerMode } from "../api/client";
import type { ComposerAttachment } from "../lib/attachments";
import type { DeviceUseMode } from "../lib/deviceUse";
import { hasInvalidAttachments } from "../lib/attachments";
import { isGroupChatComposerModeEnabled } from "../lib/interAgentFeatures";
import type { MentionItem } from "../lib/mentions";
import { isResearchRunner, RESEARCH_RUNNER_ID } from "../lib/runtimeProfiles";
import { useComposerEditor } from "../hooks/useComposerEditor";
import { useComposerInteraction } from "../hooks/useComposerInteraction";
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
import { MultiAgentModeControl } from "./MultiAgentModeControl";
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
  deviceUsePinnedMode?: Exclude<DeviceUseMode, "off"> | null;
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
  deviceUsePinnedMode = null,
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
  const { composerRef, isEditorExpanded, onComposerFocus, onToolbarPointerDown } = useComposerInteraction(editorRef);
  const pendingCaretIndexRef = useRef<number | null>(null);
  const {
    appMentionPickerQuery,
    appPickerButtonRef,
    appPickerItems,
    appPickerPanelRef,
    appPickerSearchError,
    appPickerSearchPending,
    appPickerSearchRef,
    clearDismissedMention,
    handleAppMentionPickerKey,
    insertAppMentions,
    isAppMentionPickerOpen,
    mentionTokens,
    openAppPicker,
    removeMention,
    selectAppMentionPickerItem,
    selectedAppIndex,
    updateActiveAppMentionQuery,
  } = useMentionPicker({
    caretIndex,
    editorRef,
    isEditorExpanded,
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
    isEditorExpanded,
    handleAppMentionPickerKey,
    insertAppMentions,
    mentionTokens,
    onAddAttachments,
    onChange,
    onRemoveMention: removeMention,
    onSubmit,
    pendingCaretIndexRef,
    setCaretIndex,
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
      <section
        className={`chat-ui-surface chatapp-composer ${isEmptyMode ? "is-empty-mode" : "is-docked"}`}
        data-editor-expanded={isEditorExpanded}
        onFocusCapture={onComposerFocus}
        ref={composerRef}
      >
        <form className="chatapp-form-stack" onSubmit={submit}>
          <AttachmentPreviewStrip attachments={attachments} disabled={isSending} onRemoveAttachment={onRemoveAttachment} />
          <QueuedMessageNotice queuedCount={queuedCount} queuedPreview={queuedPreview} />
          <div className={`chatapp-composer__input-shell ${isAppMentionPickerOpen ? "has-app-picker" : ""}`}>
            {isAppMentionPickerOpen ? (
              <MentionPanel
                activeIndex={Math.min(selectedAppIndex, Math.max(appPickerItems.length - 1, 0))}
                className="chatapp-mention-panel--app-picker"
                items={appPickerItems}
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
            </div>
            <div className="chatapp-composer__toolbar" onPointerDownCapture={onToolbarPointerDown}>
              <div className="chatapp-composer__tools">
                {!isolatedResearch ? (
                  <AttachmentMenu
                    attachments={attachments}
                    disabled={disabled}
                    onAddAttachments={onAddAttachments}
                    onCapturePageArea={onCapturePageArea}
                  />
                ) : null}
                <ComposerUtilities externalPanelOpen={isAppMentionPickerOpen}>
                  {!isolatedResearch && onCapturePageArea ? (
                    <button
                      aria-label="Capture page area"
                      className="chatapp-composer__tool-button chatapp-composer-utilities__capture-button"
                      disabled={disabled}
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
                      disabled={disabled}
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
                      disabled={disabled || isSending}
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
                  {!isolatedResearch && deviceUseAvailable && onSelectDeviceUseMode ? (
                    <DeviceUseControl
                      busy={deviceUseBusy}
                      locked={deviceUseLocked}
                      mode={deviceUseMode}
                      pinnedMode={deviceUsePinnedMode}
                      onModeChange={onSelectDeviceUseMode}
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
                      disabled={disabled || isSending}
                      loading={agentCatalogLoading}
                      locked={agentSelectorLocked}
                      onSelect={onSelectAgent}
                      selectedAgentTypeId={selectedAgentTypeId}
                    />
                  ) : null}
                  <ComposerRuntimeBadges
                    activeProviderId={activeProviderId}
                    disabled={disabled || isSending}
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
                hasDraft={Boolean(value.trim() || attachments.length)}
                dictationControl={
                  <ComposerDictationButton
                    chunkedDictationSupported={transcriptionChunkedDictationSupported}
                    disabled={disabled || isSending}
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
