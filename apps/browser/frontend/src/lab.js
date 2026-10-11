import {request} from "./api.js";
import {createRecords} from "./records.js";
import {showResult} from "./result-view.js";
import {activeLabSessions} from "./lab-sessions.js";

export function createLab(run) {
  const $ = selector => document.querySelector(selector);
  const sessions = createRecords($("#lab-sessions"), run);
  let flight;
  async function refresh(signal) {
    if (flight) return flight;
    flight = request({action: "status"}, {signal}).then(result => {
      const healthy = result.broker.status === "ready";
      $("#lab-health").textContent = healthy ? "Ready" : "Unavailable";
      $("#lab-health").className = `badge ${healthy ? "state-connected" : "state-failed"}`;
      $("#lab-error").hidden = healthy;
      if (!healthy) $("#lab-error").textContent = result.broker.detail || "Browser Lab is temporarily unavailable. Refresh to retry.";
      const active = activeLabSessions(result.sessions, result.broker.session_lifecycle);
      sessions(active.map(session => ({
        id: session.session_id, title: session.title || "Temporary browser session",
        status: session.mode === "maverick_dev_inspector" ? "Dev inspector" : "Read only",
        detail: session.url || session.session_id,
        action: {label: "Close session", run: async () => {
          await request({action: "session.close", session_id: session.session_id}); await refresh();
        }},
      })), "No active Lab sessions", "Temporary sessions appear here while research is running.");
    }).catch(error => {
      if (signal?.aborted) return;
      $("#lab-health").textContent = "Unavailable";
      $("#lab-health").className = "badge state-failed";
      $("#lab-error").textContent = error.message; $("#lab-error").hidden = false;
    }).finally(() => { flight = null; });
    return flight;
  }
  $("#research").onsubmit = event => {
    event.preventDefault();
    const button = $("#research button"), input = $("#research-url");
    void run(button, {run: async () => {
      $("#research-status").textContent = "Reading the page…";
      try {
        const result = await request({action: "research.open", url: input.value.trim()}, {timeoutMs: 90000});
        $("#research-status").textContent = "Page read. The temporary session has closed.";
        showResult(result);
      } catch (error) {
        $("#research-status").textContent = error.message;
      } finally { await refresh(); }
    }});
  };
  return {refresh};
}
