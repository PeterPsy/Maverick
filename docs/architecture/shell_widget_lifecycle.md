# Shell widget lifecycle

Base Shell owns widget mounting and visibility; apps own widget content and
in-memory state. Ordinary app navigation must not replace an initialized widget
document. Core launch tickets and exact origin/source validation remain required
for each new document.

## Sidebar widgets

Primary and footer slots retain one document per visited, visible registry app.
An unavailable or sidebar-disabled registry app is removed from these slots.
Changing active app hides the old document and reveals the existing target.
Context and theme updates use the existing authenticated message relay.

Footer primary-action callbacks subscribe to state and do not participate in
discovery or context creation. A footer caches state only for its exact frame
key, including workspace, authenticated generation, widget, context and frontend
revision. Changing the subscriber republishes that state without another launch.
Hidden footers may update their cache but cannot publish to the current app's
header. A changed frame key or launch error makes the action unavailable until
the new frame publishes authoritative state.

AppShell clears the old mobile action in a layout effect before the active
footer's passive subscription replay. This prevents the parent reset from
overwriting an already loaded footer's action. The sidebar need not be open for
the current app's mobile action to be available.

The mobile footer always keeps the same parent. Chat's optional theme control
changes the layout class and sibling controls, not the ancestry of its iframes.

## Contextual Chat

Chat declares one `chat-floating` widget of kind `shell.contextual.chat`.
Base Shell discovers it once and keeps the same authenticated frame while the
payload's `mode` changes between overlay, right dock and mobile fullscreen.
Placement, labels, size and context change without changing discovery identity,
launch token, React ancestry or iframe document. Dock requests also retain the
last overlay dimensions, so returning to overlay does not wait for a resize. First use remains lazy; a closed
mobile panel or initial shell entry in Chat does not launch the widget.

Chat owns the complete window stack and is its only layout-persistence writer.
Every window keeps its stable id and mounted controller during placement changes.
Dock/mobile reveal one window and make other windows hidden and inert; returning
to overlay restores the stack. Drafts, references, attachments, transcript scroll,
agent selections and pending submission identities stay in the same RAM objects.
There is no serialized draft handoff, persistent send queue or replay on reload.
The persisted v1 layout contains only ids, collapsed state and draft project
metadata; reload does not restore unsent text or file bytes.

The window header shows the operational app context and can pin its app/params
snapshot. Pinning changes only that window's context; following navigation again
uses the current host context without changing draft or thread identity.

A repeated context update is not a thread-selection command. Existing window
identity wins over the shell's remembered thread id; active-thread changes are
accepted only for an explicit matching navigation scope. Choosing a conversation
reveals its existing window or creates one and minimizes the previous window.
“Open in another window” leaves the previous window expanded. Close/minimize keep
windows recoverable, including unsent work. Deletion changes matching windows
only after the server succeeds; failures preserve selection and show a local
error. Deleting a different conversation never changes the current conversation.

The whole contextual document receives authenticated visibility updates. Hidden
windows also disable Chat's visibility context, suspending live reads, runtime
prewarm and reference preparation while retaining the draft. Closing mobile Chat
makes the covered workspace inert through the closing animation and restores
focus to the header launcher; the header remains available. The dock resize
control exposes a keyboard-operable vertical separator with width values.

Desktop panels share a viewport budget reserving 560 CSS pixels for the workspace
plus rail and panel spacing. The dock falls back to overlay if its minimum width
cannot fit; the sidebar falls back to the rail if both minima cannot fit. Saved
width/mode preferences remain unchanged and resume when space returns.

Changing workspace/authenticated generation removes retained placement frames
before rendering the new scope. Logout removes the authenticated shell tree.
App-owned frontend/runtime refresh and explicit retry still replace the affected
documents; ordinary context, theme, callbacks and app navigation do not.

## Verification

Unit tests cover subscriber replacement, frame-key resets, lazy placement mounts,
scope cleanup and stable mobile footer ancestry. The built-shell browser fixture
uses real isolated iframes and launch/bootstrap requests. It checks document
identity, draft and scroll preservation, hidden visibility, overlay/dock/mobile
continuity and zero new launch tickets for warm app navigation.

Run `npm run test:widget-lifecycle` from `apps/base-shell` after building its
frontend. This fixture checks shell lifecycle; Chat's own visibility tests cover
its live read suspension.

Chat's real-composer browser coverage exercises mode changes with an unsent draft
and file attachment, stable editor DOM identity, multiple retained windows and
zero submissions caused by mode changes. Focus and layout coverage also uses
the mounted shell fixture at desktop and mobile sizes.
