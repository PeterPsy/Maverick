import {platforms} from "./platforms.mjs";

const reserved = new Set(["accounts", "direct", "api", "challenge", "checkpoint", "oauth", "settings"]);

const blocked = new Set([...reserved,"account","messages","messaging","login","login.php","logout","signin","signup","security","notifications","compose","intent","dialogs","payment","payments","trade","trading"]);
export function platformForUrl(value) {
  try {const host=new URL(value).hostname;return Object.keys(platforms).find(key=>platforms[key].hosts.includes(host)) || null;}catch{return null;}
}
export function platformUrl(value,expectedPlatform=null) {
  if(typeof value !== "string" || value.length>2048 || value !== value.trim() || /[\\\s\u0000-\u001f]/u.test(value))throw new Error("invalid_platform_url");
  const url=new URL(value),platform=platformForUrl(value);
  if(url.protocol !== "https:" || url.port || url.username || url.password || !platform || expectedPlatform && platform !== expectedPlatform)throw new Error("shared_platform_scope_required");
  const rawPath=value.slice(value.indexOf("://")+3).replace(/^[^/]*$/u,"/").replace(/^[^/]*/u,"").split(/[?#]/u)[0] || "/";
  const parts=rawPath.replace(/^\/|\/$/gu,"").split("/");
  if(rawPath.includes("%") || rawPath.includes("//") || parts.some(p=>[".",".."].includes(p) || blocked.has(p.toLowerCase()) || p.toLowerCase().startsWith("security-check")))throw new Error("platform_route_unavailable");
  const spec=platforms[platform];
  if(!spec.paths.some(pattern=>new RegExp(`^(?:${pattern})$`,"u").test(rawPath)))throw new Error("platform_route_unavailable");
  const query=new URLSearchParams();
  if([...url.searchParams].length>30)throw new Error("platform_query_limit");
  for(const [key,value] of url.searchParams)if(spec.query_keys.includes(key)) {
    if(value.length>500 || /[\u0000-\u001f]/u.test(value))throw new Error("platform_query_limit");query.append(key,value);
  }
  url.pathname=rawPath.endsWith("/") || /\.(?:html|php)$/u.test(parts.at(-1)) ? rawPath : `${rawPath}/`;
  if(platform === "twitter")url.hostname="x.com";
  if(platform === "reddit")url.hostname="www.reddit.com";
  if(platform === "youtube" && url.hostname === "youtu.be") {url.hostname="www.youtube.com";url.pathname=parts[0] ? "/watch" : "/";for(const key of [...query.keys()])query.delete(key);if(parts[0])query.set("v",parts[0]);}
  else if(platform === "youtube" && url.pathname === "/watch/") {url.hostname="www.youtube.com";url.pathname="/watch";}
  url.search=query.toString();url.hash="";return url.href;
}

export function sharedTabUrl(value, binding, agentTabUrl) {
  if (binding.allowedPlatforms?.length) {
    if (value === agentTabUrl) return "";
    const url = platformUrl(value);
    if (!binding.allowedPlatforms.includes(platformForUrl(url))) throw new Error("shared_platform_scope_required");
    return url;
  }
  return platformUrl(value, binding.platform);
}

export function connectorUrl(value) {
  const url = new URL(value);
  if (url.username || url.password || !(url.protocol === "https:" || url.protocol === "http:" && (url.hostname === "127.0.0.1" || url.hostname === "localhost" || url.hostname.endsWith(".localhost")))) throw new Error("secure_connector_url_required");
  if (url.pathname !== "/app/browser") throw new Error("browser_connector_url_required");
  const domain = url.searchParams.get("frame_domain");
  if (domain && (!/^[a-z0-9.-]+$/u.test(domain) || domain.split(".").some(part => !part || part.startsWith("-") || part.endsWith("-")))) throw new Error("invalid_frame_domain");
  url.search = "?connector=1";
  if (domain) url.searchParams.set("frame_domain", domain);
  url.hash = "";
  return url;
}

export function connectorOrigins(url) {
  if (url.protocol === "https:") return [url.origin + "/*", `https://*.sidecars.${url.searchParams.get("frame_domain") || url.hostname}/*`];
  return [url.origin + "/*", "http://localhost/*", "http://127.0.0.1/*", "http://*.localhost/*"];
}

export function connectorFrameUrl(value, origin, domain) {
  try {
    const url = new URL(value), platform = new URL(origin);
    const local = platform.protocol === "http:" && ["localhost", "127.0.0.1"].includes(platform.hostname);
    const host = url.hostname;
    const isolated = /^af-[a-f0-9]{24}$/u.test(host.split(".")[0]) && host.slice(host.indexOf(".")) === `.sidecars.${domain || platform.hostname}`;
    if (url.username || url.password || url.protocol !== platform.protocol || url.port !== platform.port || !(isolated || local && ["localhost", "127.0.0.1"].includes(host))) return false;
    return ["/apps/browser/", "/apps/browser/index.html"].includes(url.pathname);
  } catch { return false; }
}

export function sameConnectorFrame(sender, binding) {
  return sameConnector(sender.tab, binding) && sender.frameId === binding.connectorFrameId
    && sender.documentId === binding.connectorDocumentId && Boolean(binding.connectorDocumentId)
    && connectorFrameUrl(sender.url, binding.origin, binding.frameDomain) && new URL(sender.url).origin === binding.connectorFrameOrigin;
}

export function sameConnector(tab, binding) {
  try {
    const url = connectorUrl(tab.url);
    return tab.id === binding.connectorTabId && url.origin === binding.origin && url.pathname === binding.path
      && new URL(tab.url).searchParams.get("connector") === "1";
  } catch { return false; }
}

export const observationActions = new Set(["navigate", "snapshot", "content.read", "scroll", "screenshot", "video.frame", "video.analyze", "content.collect", "tabs", "wait_for"]);

export function boundedCommand(command) {
  if (!command || !observationActions.has(command.action) || typeof command.operation_id !== "string") throw new Error("command_unavailable");
  const p = command.parameters || {};
  const fields = {
    navigate: ["url"], snapshot: ["max_chars", "max_items"], "content.read": ["max_chars", "max_items"],
    scroll: ["direction", "pixels", "steps", "settle_ms", "target"], screenshot: ["full_page"],
    "video.frame": ["video_index", "time_seconds"], "video.analyze": ["video_index", "frame_count", "max_seconds", "include_audio", "save_evidence"],
    tabs: [], wait_for: ["state", "timeout_ms"],
    "content.collect": ["urls","max_items","max_batches"],
  };
  if (Object.keys(p).some(key => !fields[command.action].includes(key))) throw new Error("command_field_unavailable");
  const limits = {max_chars: [1,100000], max_items: [1,200], max_batches: [1,40], pixels: [1,2000], steps: [1,5], settle_ms: [0,1500], video_index: [0,199], frame_count: [1,12], max_seconds: [1,180], timeout_ms: [1,15000]};
  for (const [key, [min,max]] of Object.entries(limits)) if (key in p && (!Number.isInteger(p[key]) || p[key] < min || p[key] > max)) throw new Error(`invalid_${key}`);
  for (const key of ["include_audio", "save_evidence", "full_page"]) if (key in p && typeof p[key] !== "boolean") throw new Error(`invalid_${key}`);
  if (p.full_page) throw new Error("viewport_capture_only");
  if ("time_seconds" in p && (typeof p.time_seconds !== "number" || !Number.isFinite(p.time_seconds) || p.time_seconds < 0 || p.time_seconds > 86400)) throw new Error("invalid_time_seconds");
  if ("direction" in p && !["up", "down"].includes(p.direction) || "target" in p && !["auto", "document"].includes(p.target)) throw new Error("invalid_scroll");
  if ("state" in p && !["load", "domcontentloaded"].includes(p.state)) throw new Error("invalid_wait_state");
  if (command.action === "navigate") platformUrl(p.url);
  if (command.action === "content.collect") {
    if(!Array.isArray(p.urls) || p.urls.length<1 || p.urls.length>2)throw new Error("invalid_collection_urls");
    for(const url of p.urls)platformUrl(url,platformForUrl(p.urls[0]));
  }
  return command;
}
