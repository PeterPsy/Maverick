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

Overlay, right dock and mobile fullscreen are separate declared widget surfaces.
Each placement mounts on its first visible use and then retains its document
when another placement or the main Chat app is active. A mobile panel closing
also retains its initialized document. Initial shell entry in Chat and a mobile
panel that has never opened do not launch these widgets.

At most three placement documents are retained in one authenticated workspace
scope. Each keeps its own draft, attachments, transcript and scroll in app-owned
memory. Existing Chat thread/context messages still coordinate selected threads;
keeping a document does not copy one placement's unsent draft to another.

Inactive placements are hidden and inert. They receive
`maverick.app.visibility-changed` with `visible: false`; app visibility observers
suspend live reads and nonessential polling. Late inactive navigation, dock and
active-thread callbacks cannot change the shell's current surface. Reopening
reveals the same document and lets the app resume its live transports.

Changing workspace/authenticated generation removes retained placement frames
before rendering the new scope. Logout removes the authenticated shell tree.
App-owned frontend/runtime refresh and explicit retry still replace the affected
documents; ordinary context, theme, callbacks and app navigation do not.

## Verification

Unit tests cover subscriber replacement, frame-key resets, lazy placement mounts,
scope cleanup and stable mobile footer ancestry. The built-shell browser fixture
uses real isolated iframes and launch/bootstrap requests. It checks document
identity, draft and scroll preservation, hidden visibility, overlay/dock/mobile
navigation and zero new launch tickets for warm app navigation.

Run `npm run test:widget-lifecycle` from `apps/base-shell` after building its
frontend. This fixture checks shell lifecycle; Chat's own visibility tests cover
its live read suspension.
