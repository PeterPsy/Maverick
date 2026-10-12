let dirtyControls = new WeakSet<Element>();
const pageDrafts = new Map<string, Element>();

export function clearSettingsDomCache(root = document.getElementById('app')) {
  pageDrafts.clear();
  dirtyControls = new WeakSet<Element>();
  root?.replaceChildren();
}

export function rememberSettingsDrafts(root: HTMLElement) {
  const remember = (event: Event) => {
    if (event.target instanceof Element && !event.target.hasAttribute('data-settings-controlled')) {
      dirtyControls.add(event.target);
      const status = event.target.closest('form, #workspace-assignments')?.querySelector('[data-action-status]');
      if (status) status.textContent = 'Unsaved changes';
    }
  };
  root.addEventListener('input', remember, true);
  root.addEventListener('change', remember, true);
}

export function clearSettingsDrafts(selector: string | Element) {
  const roots = typeof selector === 'string' ? [
    ...document.querySelectorAll(selector),
    ...Array.from(pageDrafts.values()).flatMap(page => [
      ...(page.matches(selector) ? [page] : []), ...page.querySelectorAll(selector)
    ])
  ] : [selector];
  roots.forEach((root) => {
    dirtyControls.delete(root);
    root.querySelectorAll('[data-action-status]').forEach(status => { status.textContent = ''; status.setAttribute('role', 'status'); });
    root.querySelectorAll('input, select, textarea').forEach((control) => dirtyControls.delete(control));
  });
}

// Keep controls, disclosure state, scroll containers and React islands alive.
// Keys are app-owned domain identities; a different page/user gets fresh controls.
export function patchSettingsDom(root: HTMLElement, html: string) {
  const focused = document.activeElement as HTMLElement | null;
  const selection = focused instanceof HTMLInputElement || focused instanceof HTMLTextAreaElement
    ? [focused.selectionStart, focused.selectionEnd] : null;
  const template = document.createElement('template');
  template.innerHTML = html;
  patchChildren(root, template.content);
  if (focused?.isConnected && document.activeElement !== focused) {
    focused.focus({ preventScroll: true });
    if (selection && selection[0] !== null && selection[1] !== null) {
      (focused as HTMLInputElement).setSelectionRange(selection[0], selection[1]);
    }
  }
}

function key(node: Node): string {
  if (!(node instanceof Element)) return '';
  return node.getAttribute('data-render-key') || node.id
    || ['data-settings-model-accordion', 'data-hosted-model-accordion', 'data-runtime-row',
      'data-workspace-row', 'data-app-row', 'data-dependency-row', 'data-agentic-provider-group',
      'data-hosted-provider-group', 'data-execution-family'].map((name) => {
        const value = node.getAttribute(name);
        return value === null ? '' : `${name}:${value}`;
      }).find(Boolean) || (node.classList.length ? `${node.tagName}:${Array.from(node.classList).filter(name => !name.startsWith('is-')).join(' ')}` : '');
}

function compatible(left: Node, right: Node) {
  return left.nodeType === right.nodeType && left.nodeName === right.nodeName && key(left) === key(right);
}

function patchChildren(current: Node, next: Node) {
  let cursor = current.firstChild;
  for (const wanted of Array.from(next.childNodes)) {
    if (cursor && !compatible(cursor, wanted) && key(wanted)) {
      const existing = Array.from(current.childNodes).find((child) => compatible(child, wanted)) || pageDrafts.get(key(wanted));
      if (existing) { pageDrafts.delete(key(wanted)); current.insertBefore(existing, cursor); cursor = existing; }
    }
    if (!cursor || !compatible(cursor, wanted)) {
      const inserted = wanted.cloneNode(true);
      current.insertBefore(inserted, cursor);
      if (cursor && !key(cursor)) { const obsolete = cursor; cursor = cursor.nextSibling; obsolete.remove(); }
      continue;
    }
    patchNode(cursor, wanted);
    cursor = cursor.nextSibling;
  }
  while (cursor) {
    const obsolete = cursor; cursor = cursor.nextSibling;
    if (obsolete instanceof Element && key(obsolete).startsWith('page:')) {
      pageDrafts.set(key(obsolete), obsolete);
      if (pageDrafts.size > 12) pageDrafts.delete(pageDrafts.keys().next().value!);
    }
    current.removeChild(obsolete);
  }
}

function patchNode(current: Node, next: Node) {
  if (!(current instanceof Element) || !(next instanceof Element)) {
    if (current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
    return;
  }
  const dirty = dirtyControls.has(current) && !next.hasAttribute('data-settings-controlled');
  const open = current instanceof HTMLDetailsElement ? current.open : undefined;
  const draftValue = dirty && 'value' in current ? String(current.value) : undefined;
  const checked = dirty && current instanceof HTMLInputElement ? current.checked : undefined;
  if (current.matches('[data-action-status]')) return;
  for (const attribute of Array.from(current.attributes)) {
    if (current.hasAttribute('data-pending-action') && ['data-pending-action', 'aria-busy'].includes(attribute.name)) continue;
    if (!next.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
  }
  for (const attribute of Array.from(next.attributes)) {
    if (current.getAttribute(attribute.name) !== attribute.value) current.setAttribute(attribute.name, attribute.value);
  }
  if (current.closest('[data-pending-action]') && current.matches('input, button, select')) current.setAttribute('disabled', '');
  if (current.matches('[data-usage-history-chart], [data-usage-history-filters]')) return;
  patchChildren(current, next);
  if (current instanceof HTMLDetailsElement && open !== undefined) current.open = open;
  if (current instanceof HTMLInputElement) {
    current.value = draftValue ?? (next as HTMLInputElement).value;
    current.checked = checked ?? (next as HTMLInputElement).checked;
  }
  if (current instanceof HTMLSelectElement || current instanceof HTMLTextAreaElement) {
    current.value = draftValue ?? (next as HTMLSelectElement).value;
  }
}
