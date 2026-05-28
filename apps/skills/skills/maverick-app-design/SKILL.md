---
name: maverick-app-design
description: Use when creating or visually aligning a Maverick app frontend so it follows Maverick-owned design tokens, layout, sidebar widgets, search, actions, and icon conventions.
---

Use this Maverick-owned design skill when creating, porting, or visually aligning a Maverick v3 app frontend, including app-owned `base-shell` sidebar widgets and footer actions. The goal is to make the app feel native to Maverick before adding decorative flourishes.

## Reference Apps

Use these app sources as the visual contract:

- `apps/storage`: primary source for app-frame tokens, full-page workspace layout, top search, glass surfaces, file/object rows, and dense operational controls.
- `apps/chat`: primary source for chat-grade tokens, common UI primitives, sidebar ownership, contextual footer action, and app-owned shell widgets.
- `apps/agents`: primary source for search inside an iframe sidebar widget and compact sidebar list rows.
- `apps/base-shell`: source of truth for the shell frame, app rail, widget slots, mobile shell offsets, and app logo rendering.

Do not import CSS or components directly from another app. Copy the relevant token values or patterns into the app-owned frontend source and rename aliases to the app domain.

## First Pass

1. Resolve the correct app source from the Maverick root first: `apps/<app_id>`. Use workspace-local source only when the user explicitly asks for a workspace-local fork or the app exists only there.
2. Inspect `app_contract.json`, frontend entrypoints, widgets, committed `frontend/dist`, and the existing style system before editing.
3. Preserve app boundaries: `base-shell` owns only the shell frame and generic widget slots; each app owns its own sidebar body, sidebar footer, search/filter state, object creation actions, and backend calls.
4. If the app uses Tailwind/shadcn, map shadcn variables to Maverick tokens instead of accepting the default shadcn palette. Remember Radix portals are mounted outside the app root; dialog/popover overrides may need global selectors within the iframe document.
5. Keep the UI operational and dense. Do not add marketing heroes, explanatory feature text, nested cards, gradient orbs, bokeh, oversized typography, or decorative layouts.

## Core Token Baseline

Create an app-owned `frontend/src/styles/tokens.css` or equivalent. Start from the Storage/Chat values and expose app-local aliases:

```css
:root {
  color-scheme: dark;
  --maverick-bg: rgba(7, 7, 8, 1);
  --maverick-bg-strong: #171717;
  --maverick-surface: rgba(255, 255, 255, 0.055);
  --maverick-surface-hover: rgba(255, 255, 255, 0.105);
  --maverick-surface-active: rgba(255, 255, 255, 0.14);
  --maverick-border: rgba(255, 255, 255, 0.08);
  --maverick-border-strong: rgba(255, 255, 255, 0.14);
  --maverick-glass-surface: rgba(12, 12, 14, 0.58);
  --maverick-glass-highlight:
    linear-gradient(135deg, rgba(255, 255, 255, 0.08), transparent 36%),
    linear-gradient(315deg, rgba(255, 255, 255, 0.035), transparent 42%);
  --maverick-glass-edge: inset 0 0 0 1px rgba(255, 255, 255, 0.052), inset 0 1px 0 rgba(255, 255, 255, 0.09);
  --maverick-inner-edge: inset 0 0 0 1px rgba(255, 255, 255, 0.075), inset 0 1px 0 rgba(255, 255, 255, 0.14);
  --maverick-text: #ececec;
  --maverick-text-muted: rgba(236, 236, 236, 0.66);
  --maverick-text-soft: rgba(236, 236, 236, 0.42);
  --maverick-accent: #ffffff;
  --maverick-accent-soft: rgba(255, 255, 255, 0.18);
  --maverick-text-on-accent: #0a0a0b;
  --maverick-success: #9ff0ca;
  --maverick-danger: #ffb3bf;
  --maverick-card-radius: 22px;
  --maverick-control-radius: 18px;
  --maverick-font: "Avenir Next", "Sohne", "Segoe UI", Inter, ui-sans-serif, system-ui, sans-serif;

  --<app>-bg: var(--maverick-bg);
  --<app>-bg-strong: var(--maverick-bg-strong);
  --<app>-surface: var(--maverick-glass-surface);
  --<app>-surface-muted: var(--maverick-surface);
  --<app>-surface-hover: var(--maverick-surface-hover);
  --<app>-surface-active: var(--maverick-surface-active);
  --<app>-border: var(--maverick-border);
  --<app>-border-strong: var(--maverick-border-strong);
  --<app>-text: var(--maverick-text);
  --<app>-muted: var(--maverick-text-muted);
  --<app>-soft: var(--maverick-text-soft);
  --<app>-accent: var(--maverick-accent);
  --<app>-accent-soft: var(--maverick-accent-soft);
  --<app>-focus: var(--maverick-accent);
  --<app>-radius-card: var(--maverick-card-radius);
  --<app>-radius-control: var(--maverick-control-radius);
}
```

Replace `<app>` with the real app id, such as `storage`, `calendar`, or `crm`. Use the app aliases in app CSS so future app-level tuning stays local.

## Full App Frame

For a launchable workspace iframe, follow the Storage shell model:

- `height: 100dvh`, `min-height: 0`, `overflow: hidden` on the root app shell.
- `width: min(100%, 1440px)`, `max-width: 1440px`, centered with `margin: 0 auto`.
- Account for the mobile shell header with `var(--maverick-shell-mobile-content-top-offset, 0px)` in top padding or overlay calculations.
- Use `background: var(--<app>-bg)` and `font-family: var(--maverick-font)` at `:root`/`body`.
- Put scroll on the inner work area, not on `body`, unless the existing app pattern already does otherwise.
- Use glass surfaces with `background: var(--<app>-surface)`, `box-shadow: var(--maverick-glass-edge)`, and restrained borders.

## Search Outside Sidebar Iframes

When the search is in the main app iframe, use the Storage pattern:

```css
.<app>-search {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  width: min(640px, 100%);
  min-height: 44px;
  border: 1px solid var(--<app>-border);
  border-radius: 999px;
  background: var(--<app>-surface-muted);
  padding: 0 14px;
}

.<app>-search:focus-within {
  border-color: var(--<app>-focus);
  box-shadow: 0 0 0 3px var(--<app>-accent-soft);
}

.<app>-search input {
  width: 100%;
  min-width: 0;
  outline: none;
  background: transparent;
}
```

Place it in an overlay/topbar only when the app has a large scrollable work area. Keep action buttons to the right in a compact `.topbar-actions` group.

## Sidebar Widgets In Base Shell

If the app needs internal navigation, filters, folders, projects, or object lists, declare app-owned widgets in `app_contract.json` instead of putting shell-specific sidebar code in `base-shell`:

```json
{
  "widget_id": "<app>-sidebar",
  "host": "base-shell",
  "content_kinds": ["shell.sidebar.primary"],
  "frontend": { "kind": "iframe", "mount": "frontend/dist/widgets/<app>-sidebar", "spa_fallback": true },
  "actions": { "backend": true, "mcp": false, "cli": false }
}
```

Add a footer widget only when the app has a natural contextual create/import action:

```json
{
  "widget_id": "<app>-sidebar-footer",
  "host": "base-shell",
  "content_kinds": ["shell.sidebar.footer"],
  "frontend": { "kind": "iframe", "mount": "frontend/dist/widgets/<app>-sidebar-footer", "spa_fallback": true },
  "actions": { "backend": true, "mcp": false, "cli": false }
}
```

Rules for sidebar widgets:

- Widget body `html`, `body`, and root should be `width: 100%; height: 100%; overflow: hidden; background: transparent`.
- The app owns loading skeletons, empty states, row selection, row actions, and backend calls.
- On mobile row selection, post `{ type: 'maverick.shell.sidebar.close' }` to the parent when it improves focus.
- Never keep showing app-owned data from a previous workspace after the host workspace changes; rely on widget context and remount behavior.

## Search Inside Sidebar Iframes

When search is inside a `shell.sidebar.primary` iframe, use the Agents pattern, not the main Storage search:

```css
.<app>-sidebar-widget {
  --<app>-sidebar-scroll-under-bottom: 7.15rem;
  --<app>-sidebar-scroll-under-top: 3.12rem;
  --<app>-sidebar-search-height: 2.65rem;
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.<app>-sidebar-search-frame {
  position: absolute;
  top: var(--<app>-sidebar-scroll-under-top);
  left: 0;
  right: 0;
  z-index: 3;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 0.48rem;
  height: var(--<app>-sidebar-search-height);
  min-height: var(--<app>-sidebar-search-height);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 22px;
  background: rgba(12, 12, 14, 0.58);
  box-shadow: var(--maverick-inner-edge);
  backdrop-filter: blur(26px);
  -webkit-backdrop-filter: blur(26px);
  padding: 0 0.72rem;
}

.<app>-sidebar-search-frame:focus-within {
  border-color: var(--<app>-focus);
  box-shadow: 0 0 0 3px var(--<app>-accent-soft);
}

.<app>-sidebar-list {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  padding: calc(var(--<app>-sidebar-scroll-under-top) + var(--<app>-sidebar-search-height) + 0.72rem) 0 var(--<app>-sidebar-scroll-under-bottom);
  scrollbar-width: none;
}
```

Use compact rows with 22px radius, glass/active fill, muted secondary text, and a 1rem to 1.12rem icon. Avoid full cards inside the sidebar.

## Contextual Add Action

For a create/add/import action in the sidebar footer, follow Chat/Agents:

- A full-width footer button, height `2.65rem`, radius `22px`, background `rgba(12, 12, 14, 0.58)`, `box-shadow: var(--maverick-inner-edge)`, font size `0.76rem`, weight `400`.
- Use an icon or CSS plus mark; do not make a large CTA card.
- If the action should also be available from the mobile shell header, post primary action state from the footer widget and handle query/invoke messages from the shell.

```ts
const WIDGET_ID = '<app>-sidebar-footer';
const PRIMARY_ACTION_LABEL = 'New item';

function postPrimaryActionState(appId: string, available: boolean) {
  window.parent?.postMessage({
    type: 'maverick.widget.primary-action.state',
    owner_app_id: appId,
    widget_id: WIDGET_ID,
    available,
    label: PRIMARY_ACTION_LABEL,
  }, window.location.origin);
}

function openCreateFlow(appId: string) {
  window.parent?.postMessage({
    type: 'maverick.widget.open-app',
    app_id: appId,
    params: { new_item: true, new_item_request_id: crypto.randomUUID() },
  }, window.location.origin);
}

function handleShellMessage(event: MessageEvent, appId: string, available: boolean) {
  if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') {
    return;
  }
  const payload = event.data as { owner_app_id?: string; type?: string; widget_id?: string };
  if (payload.owner_app_id !== appId || payload.widget_id !== WIDGET_ID) {
    return;
  }
  if (payload.type === 'maverick.widget.primary-action.query') {
    postPrimaryActionState(appId, available);
  }
  if (payload.type === 'maverick.widget.primary-action.invoke' && available) {
    openCreateFlow(appId);
  }
}
```

Handle the resulting params in the main app through `maverick.app.navigate` without reloading the iframe. Use explicit scalar param names that match the app domain, such as `new_chat_request_id`, `new_agent_request_id`, or `new_record_request_id`.

## Buttons, Icons, Rows, And Cards

- Primary actions: white/brand fill with `var(--maverick-text-on-accent)`.
- Secondary actions: glass surface, 1px Maverick border, muted hover.
- Danger actions: soft danger background/border using `--maverick-danger`.
- Use `Material Symbols Rounded` for shell/sidebar/app registry glyphs and keep glyph names consistent between `base-shell` and App Store icon maps.
- Use `lucide-react` for ordinary React app controls when the app already uses lucide or a matching icon library.
- Cards are for repeated items, modals, and genuinely framed tools. Do not put cards inside cards.
- Keep radius at 22px for app/sidebar cells and 18px for controls unless an existing local pattern differs.
- Font weight is usually 400-600; avoid bold marketing treatments. Letter spacing should be `0` unless the local app already defines a subtle label style.

## Tailwind Or shadcn Mapping

For Tailwind/shadcn apps, map the shadcn design variables to the app aliases defined in the token baseline:

```css
:root {
  --background: var(--<app>-bg);
  --foreground: var(--<app>-text);
  --card: var(--<app>-surface-muted);
  --card-foreground: var(--<app>-text);
  --popover: rgba(18, 18, 20, 0.96);
  --popover-foreground: var(--<app>-text);
  --primary: var(--<app>-accent);
  --primary-foreground: var(--maverick-text-on-accent);
  --secondary: var(--<app>-surface-muted);
  --secondary-foreground: var(--<app>-text);
  --muted: var(--<app>-surface-muted);
  --muted-foreground: var(--<app>-muted);
  --accent: var(--<app>-surface-hover);
  --accent-foreground: var(--<app>-text);
  --border: var(--<app>-border);
  --input: var(--<app>-border-strong);
  --ring: rgba(255, 255, 255, 0.32);
  --radius: var(--<app>-radius-card);
}
```

Then add app-scoped overrides for generated utility classes only when needed for contrast or portal content. Keep those overrides local to the app iframe.

## Verification

Before finishing:

1. Run the app frontend build from the app root or official surface: `maverick app <app_id> frontend build --json` when available.
2. Run focused frontend tests when present, plus any backend/contract tests touched by sidebar/widget declarations.
3. Confirm committed `frontend/dist` references the latest assets if the app commits dist.
4. Check desktop and mobile widths for text clipping, sidebar scroll clearance, topbar overlap, and mobile shell offset.
5. For app logo/icon changes, update every relevant map consistently, usually `base-shell` and App Store helper assets, then rebuild both frontends.
