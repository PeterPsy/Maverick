import {label, node} from "./records.js";
const readable = value => String(label(value) || "Unknown").replaceAll("_", " ");

export function publicUrl(value) {
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}

function sourceLink(value, text) {
  const href = publicUrl(value);
  if (!href) return node("span", "", text || "Source unavailable");
  const link = node("a", "source-link", text || href);
  link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; return link;
}

export function appendCoverage(dialog, coverage) {
  if (typeof coverage === "string") dialog.append(node("p", "result-coverage", coverage));
  else if (coverage && typeof coverage === "object") {
    const list = node("dl", "result-facts");
    for (const [key, value] of Object.entries(coverage)) {
      if (!["string", "number", "boolean"].includes(typeof value)) continue;
      list.append(node("dt", "", readable(key)), node("dd", "", String(value)));
    }
    if (list.children.length) dialog.append(list);
  }
}

export function appendCollection(dialog, result) {
  if (!Array.isArray(result.items)) return;
  const section = node("section", "result-collection");
  section.append(node("h3", "", `${result.items.length} collected items`));
  const summary = [Number.isFinite(result.batches) ? `${result.batches} scroll batches` : null,
    result.stop_reason ? `Stopped: ${readable(result.stop_reason)}` : null].filter(Boolean).join(" · ");
  section.append(node("p", "section-note", summary));
  if (!result.items.length) section.append(node("p", "section-note", "No items found within the observed pages and scrolling limits."));
  const list = node("ol", "result-items");
  for (const item of result.items.slice(0, 200)) {
    const li = node("li", "");
    li.append(sourceLink(item.url, item.text || item.title || item.url));
    li.append(node("p", "section-note", `${label(item.kind || "item")} · ${item.content_observed ? "Content observed" : "Link observed; item content has not been read"}`));
    if (item.found_on) { const found = node("p", "section-note", "Found on "); found.append(sourceLink(item.found_on)); li.append(found); }
    list.append(li);
  }
  section.append(list);
  if (Array.isArray(result.sections) && result.sections.length) {
    section.append(node("h3", "", "Observed pages"));
    for (const page of result.sections.slice(0, 2)) {
      const row = node("div", "result-page"); row.append(sourceLink(page.source_url));
      row.append(node("p", "section-note", `${readable(page.status)} · ${page.batches ?? 0} batches · ${readable(page.stop_reason)}`)); section.append(row);
    }
  }
  for (const observation of (result.observations || []).slice(0, 2)) {
    if (!observation.text) continue;
    const details = node("details", "result-details"); details.append(node("summary", "", observation.title || "Observed page text"), node("pre", "observed-text", observation.text));
    section.append(details);
  }
  dialog.append(section);
}
