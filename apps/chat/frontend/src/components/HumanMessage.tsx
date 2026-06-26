import type { ReactNode } from "react";
import type { AppReference, ChatMessage } from "../api/client";
import { formatFileSize } from "../lib/attachments";
import { findEntityReferenceMarkers, findMentionTokens } from "../lib/mentions";
import type { MentionItem } from "../lib/mentions";
import { fallbackMatchesForAppReference, rangesOverlap } from "../lib/messageReferenceMatches";
import type { MessageMentionMatch } from "../lib/messageReferenceMatches";
import { referenceKindLabel } from "../lib/referenceKindLabels";
import { openAppParamsInShell, type ShellRouteParams } from "../lib/shellNavigation";
import { CopyMessageButton } from "./MessageCopyButton";
import { MessageFooter } from "./MessageFooter";

const URL_PARSE_BASE = "https://maverick.local";

export function HumanMessage({
  mentionItems,
  message,
  onCopyMessage,
}: {
  mentionItems: MentionItem[];
  message: ChatMessage;
  onCopyMessage: (content: string) => Promise<void>;
}) {
  return (
    <div className="chatapp-human-message">
      <div className="chatapp-message-copy-row chatapp-message-copy-row--human">
        <div className="chatapp-human-message__text">
          {renderHumanMessageContent(message.content, message.appReferences || [], mentionItems)}
        </div>
        {message.content ? <CopyMessageButton content={message.content} onCopyMessage={onCopyMessage} /> : null}
      </div>
      {message.attachments?.length ? (
        <div className="chatapp-human-message__attachments">
          {message.attachments.map((attachment) => (
            <div
              className={`chatapp-attachment-card is-readonly ${attachment.isImage ? "is-image" : ""} ${attachment.warning ? "is-invalid" : ""}`}
              key={attachment.id}
            >
              {attachment.objectUrl && message.status === "pending" ? (
                <img alt="" className="chatapp-attachment-card__preview" src={attachment.objectUrl} />
              ) : (
                <span className="chatapp-attachment-card__icon" aria-hidden="true">
                  <span className="material-symbols-rounded">{attachment.isAudio ? "audio_file" : "description"}</span>
                </span>
              )}
              <span className="chatapp-attachment-card__meta">
                <span className="chatapp-attachment-card__name">{attachment.name}</span>
                <span className="chatapp-attachment-card__detail">{formatFileSize(attachment.size)}</span>
              </span>
            </div>
          ))}
        </div>
      ) : null}
      <MessageFooter content={message.content} createdAt={message.createdAt} onCopy={onCopyMessage} />
    </div>
  );
}

function renderHumanMessageContent(content: string, appReferences: AppReference[], mentionItems: MentionItem[]) {
  const appReferenceMatches = appReferences.flatMap((reference) => fallbackMatchesForAppReference(content, reference));
  const markerMatches = fallbackMatchesForEntityReferenceMarkers(content).filter(
    (match) => !appReferenceMatches.some((referenceMatch) => rangesOverlap(referenceMatch, match)),
  );
  const referenceMatches = [...appReferenceMatches, ...markerMatches];
  const tokenMatches = findMentionTokens(content, mentionItems)
    .map((token) => ({
      kind: token.item.kind,
      id: token.item.id,
      label: token.item.label,
      appId: token.item.reference?.type === "entity" ? token.item.reference.app_id : undefined,
      deepLink: token.item.reference?.type === "entity" ? token.item.reference.deep_link : undefined,
      entityType: token.item.reference?.type === "entity" ? token.item.reference.entity_type : undefined,
      exists: token.item.reference?.type === "entity" ? token.item.reference.exists : undefined,
      summary: token.item.reference?.type === "entity" ? token.item.reference.summary : undefined,
      start: token.start,
      end: token.end,
    }))
    .filter((match) => !referenceMatches.some((referenceMatch) => rangesOverlap(referenceMatch, match)));
  const matches = [...referenceMatches, ...tokenMatches]
    .sort((left, right) => left.start - right.start)
    .filter((match, index, sorted) => index === 0 || match.start >= sorted[index - 1].end);
  if (!matches.length) {
    return content;
  }
  const segments: ReactNode[] = [];
  let cursor = 0;
  matches.forEach((match) => {
    if (match.start > cursor) {
      segments.push(content.slice(cursor, match.start));
    }
    segments.push(<MentionReferenceChip key={`${match.kind}:${match.id}:${match.start}`} match={match} />);
    cursor = match.end;
  });
  if (cursor < content.length) {
    segments.push(content.slice(cursor));
  }
  return segments;
}

function fallbackMatchesForEntityReferenceMarkers(content: string): MessageMentionMatch[] {
  return findEntityReferenceMarkers(content).map((marker) => ({
    kind: "entity",
    id: `entity:${marker.appId}:${marker.entityType}:${marker.entityId}`,
    appId: marker.appId,
    entityType: marker.entityType,
    label: marker.label || marker.entityId,
    start: marker.mentionStart ?? marker.markerStart,
    end: marker.markerEnd,
  }));
}

function MentionReferenceChip({ match }: { match: MessageMentionMatch }) {
  const className = `chatapp-message-reference-chip is-${match.kind} ${match.exists === false ? "is-missing" : ""}`;
  const title = match.kind === "entity" ? `reference: ${match.id}` : `${match.kind === "app" ? "app_id" : "skill_id"}: ${match.id}`;
  const content = (
    <>
      <span className="chatapp-message-reference-chip__kind">{referenceKindLabel(match)}</span>
      <span className="chatapp-message-reference-chip__label">{match.exists === false ? `${match.label} (missing)` : match.label}</span>
    </>
  );
  if (match.kind === "entity" && match.appId && match.deepLink) {
    return (
      <button
        className={className}
        data-reference-id={match.id}
        onClick={() => openEntityReference(match.appId || "", match.deepLink || "")}
        title={title}
        type="button"
      >
        {content}
      </button>
    );
  }
  return (
    <span className={className} data-reference-id={match.id} title={title}>
      {content}
    </span>
  );
}

function openEntityReference(appId: string, deepLink: string): void {
  const params = appRouteParamsFromDeepLink(appId, deepLink);
  if (params) {
    openAppParamsInShell(appId, params);
  }
}

function appRouteParamsFromDeepLink(appId: string, deepLink: string): ShellRouteParams | null {
  let url: URL;
  try {
    url = new URL(deepLink, URL_PARSE_BASE);
  } catch {
    return null;
  }
  const segments = url.pathname.split("/").filter(Boolean).map(decodePathSegment);
  const [routeKind, routeAppId, ...pageSegments] = segments;
  if ((routeKind !== "app" && routeKind !== "apps") || routeAppId !== appId) {
    return null;
  }
  const params: ShellRouteParams = Object.fromEntries(url.searchParams.entries());
  const appPage = pageSegments.join("/");
  if (appPage) {
    params.app_page = appPage;
  }
  return Object.keys(params).length ? params : null;
}

function decodePathSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
