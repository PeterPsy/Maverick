export async function callBackend<T>(
  body: Record<string, unknown>,
): Promise<T> {
  const response = await fetch(
    `/api/apps/${encodeURIComponent(mountedAppIdFromPath())}/backend`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  const responseText = await response.text();
  let payload: (T & { error?: string }) | null = null;
  try {
    payload = JSON.parse(responseText) as T & { error?: string };
  } catch {
    if (response.ok) throw new Error("La risposta del backend non è valida.");
  }
  if (!response.ok)
    throw new Error(
      payload?.error || `Richiesta non riuscita (${response.status})`,
    );
  if (!payload) throw new Error("La risposta del backend è vuota.");
  return payload;
}
import { mountedAppIdFromPath } from "./lib/shellNavigation";
