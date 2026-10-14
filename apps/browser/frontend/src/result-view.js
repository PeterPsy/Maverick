import {label, node} from "./records.js";
import {appendMedia} from "./result-media.js";
import {appendCollection, appendCoverage, publicUrl} from "./result-collection.js";

export function showResult(operation) {
  const previous = document.querySelector("dialog");
  if (previous) previous.close();
  const result = operation.result || operation;
  const dialog = node("dialog", "result-dialog");
  dialog.setAttribute("aria-labelledby", "result-title");
  const heading = node("div", "section-title"), title = node("h2", "", result.title || label(operation.action) || "Page result");
  title.id = "result-title";
  const close = node("button", "secondary", "Close");
  close.onclick = () => dialog.close(); heading.append(title, close); dialog.append(heading);
  if (operation.status) dialog.append(node("p", "section-note", label(operation.status)));
  const source = publicUrl(result.source_url || result.url);
  if (source) {
    const link = node("a", "source-link", source); link.href = source; link.target = "_blank"; link.rel = "noopener noreferrer";
    dialog.append(link);
  }
  if (result.error) dialog.append(node("p", "error", result.detail || label(result.error)));
  const release = appendMedia(dialog, result, window.__LOOPINO_PLATFORM_ORIGIN__ || location.origin);
  appendCollection(dialog, result);
  appendCoverage(dialog, result.coverage);
  const text = result.text || result.content || result.transcription?.text;
  if (typeof text === "string" && text) {
    const copy = node("button", "secondary result-copy", "Copy text");
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(text); copy.textContent = "Copied"; }
      catch { copy.textContent = "Select the text below to copy"; }
    };
    dialog.append(copy, node("pre", "observed-text", text));
  }
  if (result.truncated || result.coverage?.truncated) dialog.append(node("p", "section-note", "This observation is partial; some content was not captured."));
  if (Array.isArray(result.links) && result.links.length) {
    const details = node("details", "result-details"), list = node("ul", "result-links");
    details.append(node("summary", "", `${result.links.length} observed links`));
    for (const item of result.links.slice(0, 200)) {
      const href = publicUrl(item.url || item.href); if (!href) continue;
      const li = node("li", ""), link = node("a", "", item.text || item.title || href);
      link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; li.append(link); list.append(li);
    }
    details.append(list); dialog.append(details);
  }
  const details = node("details", "result-details");
  details.append(node("summary", "", "Technical details"));
  // Serialize lazily; captured media never becomes a second large DOM payload.
  details.addEventListener("toggle", () => {
    if (details.open && details.children.length === 1) details.append(node("pre", "", JSON.stringify(operation, function(key, value) {
      return key === "base64" || key === "data" && this.encoding === "base64" ? "[captured media shown above]" : value;
    }, 2)));
  });
  dialog.append(details);
  dialog.addEventListener("close", () => { release(); dialog.remove(); }, {once: true});
  document.body.append(dialog); dialog.showModal(); close.focus();
}
