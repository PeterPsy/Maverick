const reserved = new Set(["accounts", "direct", "api", "challenge", "checkpoint", "oauth", "settings"]);

export function instagramUrl(value) {
  if (typeof value !== "string" || value.length > 2048 || value !== value.trim() || /[\\\s]/u.test(value)) throw new Error("invalid_instagram_url");
  const url = new URL(value);
  if (url.protocol !== "https:" || url.hostname !== "www.instagram.com" || url.port || url.username || url.password) throw new Error("instagram_scope_required");
  // Reject normalization tricks before URL parsing erases dot segments.
  const rawPath = value.slice(value.indexOf("www.instagram.com") + "www.instagram.com".length).split(/[?#]/u)[0];
  if (rawPath.includes("%") || rawPath.includes("//") || rawPath.split("/").some(s => s === "." || s === "..")) throw new Error("invalid_instagram_route");
  const parts = url.pathname.replace(/^\/|\/$/gu, "").split("/");
  const user = s => /^[A-Za-z0-9._]{1,30}$/u.test(s) && !reserved.has(s.toLowerCase()) && ![".", ".."].includes(s);
  const valid = parts.length === 1 && user(parts[0]) || parts.length === 2 && (
    ["p", "reel"].includes(parts[0]) && /^[A-Za-z0-9_-]{1,80}$/u.test(parts[1]) || user(parts[0]) && parts[1] === "reels"
  );
  if (!valid) throw new Error("instagram_route_unavailable");
  return `https://www.instagram.com/${parts.join("/")}/`;
}

export function connectorUrl(value) {
  const url = new URL(value);
  if (url.username || url.password || !(url.protocol === "https:" || url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) throw new Error("secure_connector_url_required");
  if (url.pathname !== "/apps/browser/" && url.pathname !== "/apps/browser/index.html") throw new Error("browser_connector_url_required");
  url.search = "?connector=1";
  url.hash = "";
  return url;
}

export function sameConnector(tab, binding) {
  try {
    const url = connectorUrl(tab.url);
    return tab.id === binding.connectorTabId && url.origin === binding.origin && url.pathname === binding.path
      && new URL(tab.url).searchParams.get("connector") === "1";
  } catch { return false; }
}

export const observationActions = new Set(["navigate", "snapshot", "content.read", "scroll", "screenshot", "video.frame", "video.analyze", "instagram.collect", "tabs", "wait_for"]);

export function boundedCommand(command) {
  if (!command || !observationActions.has(command.action) || typeof command.operation_id !== "string") throw new Error("command_unavailable");
  const p = command.parameters || {};
  const fields = {
    navigate: ["url"], snapshot: ["max_chars", "max_items"], "content.read": ["max_chars", "max_items"],
    scroll: ["direction", "pixels", "steps", "settle_ms", "target"], screenshot: ["full_page"],
    "video.frame": ["video_index", "time_seconds"], "video.analyze": ["video_index", "frame_count", "max_seconds", "include_audio", "save_evidence"],
    "instagram.collect": ["username", "max_items", "max_batches", "include_reels"], tabs: [], wait_for: ["state", "timeout_ms"],
  };
  if (Object.keys(p).some(key => !fields[command.action].includes(key))) throw new Error("command_field_unavailable");
  const limits = {max_chars: [1,100000], max_items: [1,200], max_batches: [1,40], pixels: [1,2000], steps: [1,5], settle_ms: [0,1500], video_index: [0,199], frame_count: [1,12], max_seconds: [1,180], timeout_ms: [1,15000]};
  for (const [key, [min,max]] of Object.entries(limits)) if (key in p && (!Number.isInteger(p[key]) || p[key] < min || p[key] > max)) throw new Error(`invalid_${key}`);
  for (const key of ["include_audio", "save_evidence", "include_reels", "full_page"]) if (key in p && typeof p[key] !== "boolean") throw new Error(`invalid_${key}`);
  if (p.full_page) throw new Error("viewport_capture_only");
  if ("time_seconds" in p && (typeof p.time_seconds !== "number" || !Number.isFinite(p.time_seconds) || p.time_seconds < 0 || p.time_seconds > 86400)) throw new Error("invalid_time_seconds");
  if ("direction" in p && !["up", "down"].includes(p.direction) || "target" in p && !["auto", "document"].includes(p.target)) throw new Error("invalid_scroll");
  if ("state" in p && !["load", "domcontentloaded"].includes(p.state)) throw new Error("invalid_wait_state");
  if (command.action === "navigate") instagramUrl(p.url);
  if (command.action === "instagram.collect") instagramUrl(`https://www.instagram.com/${p.username}/`);
  return command;
}
