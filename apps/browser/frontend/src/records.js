export const labels = {
  "content.read": "Read page", "content.collect": "Collect content", snapshot: "Page snapshot",
  navigate: "Navigate", scroll: "Scroll page", screenshot: "Screenshot", "video.frame": "Video frame",
  "video.analyze": "Video analysis", tabs: "Inspect tabs", wait_for: "Wait for page",
  click:"Click",type:"Fill field",press_key:"Press key",hover:"Hover",select_option:"Select option",set_checked:"Set checkbox",
  processing_media: "Saving media", queued: "Queued", running: "Running", completed: "Completed",
  failed: "Failed", expired: "Expired", cancelled: "Cancelled", connecting: "Connecting",
  connected: "Connected", offline: "Offline", revoked: "Stopped",
};
export const label = value => labels[value] || value;
export const timestamp = seconds => new Date(seconds * 1000).toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"});
export function node(tag, className, text) {
  const result = document.createElement(tag);
  result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}

// Reuse rows and action buttons so heartbeats do not reset focus or selection.
export function createRecords(container, run) {
  const rows = new Map();
  const empty = node("div", "empty");
  return (records, emptyTitle, emptyDetail = "") => {
    const ids = new Set(records.map(record => record.id));
    for (const [id, row] of rows) if (!ids.has(id)) { row.root.remove(); rows.delete(id); }
    empty.remove();
    if (!records.length) {
      empty.replaceChildren(node("strong", "", emptyTitle), node("p", "", emptyDetail));
      container.replaceChildren(empty);
      return;
    }
    container.querySelectorAll(":scope > .empty").forEach(element => element.remove());
    records.forEach((record, index) => {
      let row = rows.get(record.id);
      if (!row) {
        row = {root: node("article", "row"), title: node("strong", "row-title"),
          detail: node("p", "row-detail"), status: node("span", "badge"), button: node("button", "secondary")};
        const copy = node("div", "row-copy"), heading = node("div", "row-heading");
        heading.append(row.title, row.status); copy.append(heading, row.detail);
        row.root.append(copy, row.button); rows.set(record.id, row);
        row.button.onclick = () => run(row.button, row.action);
      }
      if (row.title.textContent !== record.title) row.title.textContent = record.title;
      if (row.detail.textContent !== record.detail) row.detail.textContent = record.detail;
      row.status.textContent = label(record.status);
      row.status.className = `badge state-${record.status}`;
      row.action = record.action;
      row.button.hidden = !record.action;
      row.button.dataset.label = record.action?.label || "";
      if (!row.button.disabled && record.action) row.button.textContent = record.action.label;
      row.button.setAttribute("aria-label", `${record.action?.label || "Action"}: ${record.title}`);
      if (container.children[index] !== row.root) container.insertBefore(row.root, container.children[index] || null);
    });
  };
}
