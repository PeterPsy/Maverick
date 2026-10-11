import { useEffect, useState } from "react";
import { googlePost } from "../api";
import { googleAuthorizationTarget } from "../lib/googleAuth";
import { BrandMark } from "./BrandMark";
import { googleCallbackMessage } from "./GoogleServices";

const initial = new URL(window.location.href);
export const isGoogleBrowserHandoff = initial.searchParams.has("google_handoff") || initial.searchParams.has("google_handoff_done");
let launchValues = initial.searchParams.has("google_handoff") ? initial.hash.slice(1).split(".") : null;
const callbackError = initial.searchParams.get("google_error");
if (isGoogleBrowserHandoff) {
  window.history.replaceState(null, "", initial.searchParams.has("google_handoff") ? "/?google_handoff=1"
    : "/?google_handoff_done=1" + (callbackError ? "&google_error=" + encodeURIComponent(callbackError) : ""));
  const meta = document.createElement("meta"); meta.name = "referrer"; meta.content = "no-referrer"; document.head.append(meta);
}
let launch: Promise<void> | null = null;
function openGoogle() {
  if (!launch) {
    const values = launchValues; launchValues = null;
    launch = (async () => {
      if (!values || values.length !== 2 || values.some(value => !/^[A-Za-z0-9_-]{32,128}$/.test(value))) throw new Error("Invalid handoff.");
      const result = await googlePost<{ authorization_url: string }>("/api/auth/google/handoff", { state: values[0], handoff: values[1] });
      window.location.replace(googleAuthorizationTarget(result.authorization_url));
    })();
  }
  return launch;
}

export function GoogleBrowserHandoff() {
  const starting = initial.searchParams.has("google_handoff");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    if (starting) void openGoogle().catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [starting]);
  const error = googleCallbackMessage(callbackError);
  return <main className="bs-google-handoff">
    <BrandMark className="bs-google-handoff__brand" variant="mark" />
    <h1>{failed || error ? "Google connection incomplete" : starting ? "Opening Google…" : "Google connected"}</h1>
    <p role={failed || error ? "alert" : "status"}>{failed ? "This connection has expired or was already opened. Return to Maverick and try again."
      : error ?? (starting ? "Continue with Google in this browser." : "Return to Maverick. Your connection will update automatically.")}</p>
    {!starting && <p>You can close this browser tab.</p>}
  </main>;
}
