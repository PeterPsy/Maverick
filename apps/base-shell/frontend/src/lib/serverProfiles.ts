export type ServerProfile = { id: string; name: string; origin: string; current: boolean };
export type ServerProfiles = { native: boolean; profiles: ServerProfile[] };
type ServerBridge = { postMessage: (message: Record<string, unknown>) => Promise<unknown> };

function bridge(): ServerBridge | undefined {
  const handlers = (window as unknown as { webkit?: { messageHandlers?: {
    maverickServers?: ServerBridge; sensesHost?: unknown; maverickDeviceUse?: unknown; maverickExternalURL?: unknown;
  } } }).webkit?.messageHandlers;
  if (!handlers?.maverickServers && (handlers?.sensesHost || handlers?.maverickDeviceUse || handlers?.maverickExternalURL)) {
    throw new Error("Update the Maverick native app to manage servers. Your current login will be preserved.");
  }
  return handlers?.maverickServers;
}

export function normalizeServerOrigin(value: string): string {
  const url = new URL(value.trim());
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("Enter an HTTPS server address without a path, query or credentials.");
  }
  return url.origin;
}

const storageKey = "maverick.server-bookmarks.v1";
function bookmarks(): ServerProfile[] {
  const current = { id: window.location.origin, name: "This Maverick", origin: window.location.origin, current: true };
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(storageKey) ?? "[]");
    if (!Array.isArray(saved)) return [current];
    return [current, ...saved.filter((item): item is ServerProfile => {
      if (!item || typeof item.id !== "string" || typeof item.name !== "string" || typeof item.origin !== "string") return false;
      try { return normalizeServerOrigin(item.origin) === item.origin && item.origin !== current.origin; } catch { return false; }
    }).map(item => ({ ...item, current: false }))];
  } catch { return [current]; }
}

function decodeNative(value: unknown): ServerProfiles {
  const data = value as { profiles?: ServerProfile[] };
  if (!Array.isArray(data?.profiles) || !data.profiles.length || data.profiles.some(item =>
    !item || typeof item.id !== "string" || typeof item.name !== "string" || typeof item.origin !== "string" || typeof item.current !== "boolean")) {
    throw new Error("Update the Maverick native app to manage servers.");
  }
  return { native: true, profiles: data.profiles };
}

export async function getServerProfiles(): Promise<ServerProfiles> {
  const native = bridge();
  return native ? decodeNative(await native.postMessage({ action: "list" })) : { native: false, profiles: bookmarks() };
}

export async function saveServerProfile(name: string, address: string, id?: string): Promise<ServerProfiles> {
  const label = name.trim();
  if (!label || label.length > 80) throw new Error("Choose a server name between 1 and 80 characters.");
  const origin = normalizeServerOrigin(address);
  const native = bridge();
  if (native) return decodeNative(await native.postMessage({ action: id ? "rename" : "add", id, name: label, origin }));
  const profiles = bookmarks();
  if (id && id !== window.location.origin) {
    const item = profiles.find(profile => profile.id === id);
    if (!item) throw new Error("Server no longer saved.");
    item.name = label;
  } else if (!id && !profiles.some(profile => profile.origin === origin)) {
    profiles.push({ id: origin, name: label, origin, current: false });
  } else throw new Error("This server is already saved.");
  localStorage.setItem(storageKey, JSON.stringify(profiles.filter(profile => !profile.current)));
  return { native: false, profiles };
}

export async function removeServerProfile(id: string): Promise<ServerProfiles> {
  const native = bridge();
  if (native) return decodeNative(await native.postMessage({ action: "remove", id }));
  const profiles = bookmarks();
  if (profiles.find(profile => profile.id === id)?.current) throw new Error("Switch servers before removing this profile.");
  localStorage.setItem(storageKey, JSON.stringify(profiles.filter(profile => !profile.current && profile.id !== id)));
  return { native: false, profiles: profiles.filter(profile => profile.id !== id) };
}

export async function switchServerProfile(profile: ServerProfile): Promise<void> {
  const native = bridge();
  if (native) { await native.postMessage({ action: "switch", id: profile.id }); return; }
  window.location.assign(new URL("/app/chat", normalizeServerOrigin(profile.origin)).href);
}

export async function clearNativeServerSession(): Promise<void> {
  const native = bridge();
  if (native) await native.postMessage({ action: "logout" });
}
