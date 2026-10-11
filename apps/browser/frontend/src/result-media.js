import {node} from "./records.js";

const imageTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
const audioTypes = new Set(["audio/webm", "audio/ogg", "audio/wav"]);
const seconds = value => Number.isFinite(value) ? `${Math.round(value * 100) / 100}s` : null;

function capturedUrl(item, types, release) {
  const type = item.mime_type || item.content_type;
  const encoded = item.base64 || (item.encoding === "base64" ? item.data : null);
  if (!types.has(type) || typeof encoded !== "string" || encoded.length > 16 * 1024 * 1024) return null;
  try {
    const bytes = Uint8Array.from(atob(encoded), char => char.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], {type}));
    release.push(url); return url;
  } catch { return null; }
}

function savedLink(item, text, platformOrigin) {
  if (!item.storage?.file_id) return null;
  const link = node("a", "source-link", text);
  const url = new URL("/app/storage", platformOrigin);
  url.searchParams.set("file_id", item.storage.file_id);
  link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
  return link;
}

export function appendMedia(dialog, result, platformOrigin) {
  const release = [];
  const frames = Array.isArray(result.frames) ? result.frames.slice(0, 12) :
    imageTypes.has(result.mime_type) ? [result] : [];
  if (frames.length || result.audio || Number.isFinite(result.duration_seconds)) {
    const section = node("section", "result-media");
    section.append(node("h3", "", frames.length === 1 && !result.audio ? "Captured image" : "Video observation"));
    const timing = [Number.isFinite(result.covered_seconds) ? `${seconds(result.covered_seconds)} observed` : null,
      Number.isFinite(result.duration_seconds) ? `${seconds(result.duration_seconds)} duration` : null].filter(Boolean);
    if (timing.length) section.append(node("p", "section-note", timing.join(" · ")));
    const grid = node("div", "result-frames");
    for (const [index, frame] of frames.entries()) {
      const caption = seconds(frame.time_seconds) ? `Frame at ${seconds(frame.time_seconds)}` : `Capture ${index + 1}`;
      const figure = node("figure", "result-frame"), url = capturedUrl(frame, imageTypes, release);
      if (url) {
        const image = node("img", ""); image.src = url; image.alt = caption;
        image.loading = "lazy"; image.decoding = "async"; figure.append(image);
      }
      figure.append(node("figcaption", "", [caption, frame.width && frame.height ? `${frame.width} × ${frame.height}` : null].filter(Boolean).join(" · ")));
      const link = savedLink(frame, "Open saved frame in Storage", platformOrigin);
      if (link) figure.append(link);
      if (!url && !link) figure.append(node("p", "section-note", "Image unavailable in this result."));
      grid.append(figure);
    }
    section.append(grid);
    if (result.audio) {
      section.append(node("h3", "", "Captured audio"));
      const audio = result.audio, url = capturedUrl(audio, audioTypes, release);
      if (url) {
        const player = node("audio", ""); player.src = url; player.controls = true; player.preload = "none"; section.append(player);
      }
      const timing = [seconds(audio.start_time_seconds), seconds(audio.end_time_seconds)].filter(Boolean).join(" – ");
      if (timing || seconds(audio.duration_seconds)) section.append(node("p", "section-note", timing || `${seconds(audio.duration_seconds)} captured`));
      const link = savedLink(audio, "Open saved audio in Storage", platformOrigin);
      if (link) section.append(link);
      if (!url && !link) section.append(node("p", "section-note", "Audio unavailable in this result."));
    }
    if (result.transcription?.status && !result.transcription.text) section.append(node("p", "section-note", `Transcript ${result.transcription.status.replaceAll("_", " ")}.`));
    dialog.append(section);
  }
  return () => { for (const url of release) URL.revokeObjectURL(url); };
}
