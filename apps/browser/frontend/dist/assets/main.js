const state = {
  status: null,
  lastPolicy: null,
};

const elements = {
  brokerSummary: document.querySelector("#broker-summary"),
  sessionCount: document.querySelector("#session-count"),
  auditCount: document.querySelector("#audit-count"),
  policyStatus: document.querySelector("#policy-status"),
  preflightForm: document.querySelector("#preflight-form"),
  urlInput: document.querySelector("#url-input"),
  modeInput: document.querySelector("#mode-input"),
  refreshButton: document.querySelector("#refresh-button"),
  snapshotOutput: document.querySelector("#snapshot-output"),
};

async function callBackend(body) {
  const response = await fetch("/api/apps/browser/backend", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  return payload;
}

async function refreshStatus() {
  try {
    const payload = await callBackend({ action: "status" });
    const status = payload.json || payload;
    state.status = status;
    elements.brokerSummary.textContent = `${status.broker?.provider || "playwright_lab"}: ${status.broker?.status || "unknown"}`;
    elements.sessionCount.textContent = String(status.session_count || 0);
    elements.auditCount.textContent = String(status.audit_count || 0);
  } catch (error) {
    elements.brokerSummary.textContent = "Backend unavailable";
    elements.snapshotOutput.textContent = String(error);
  }
}

async function preflight(event) {
  event.preventDefault();
  const url = elements.urlInput.value.trim();
  const mode = elements.modeInput.value;
  elements.policyStatus.textContent = "Checking";
  elements.policyStatus.className = "blocked";
  try {
    const payload = await callBackend({ action: "policy.preflight", url, mode });
    const policy = (payload.json || payload).policy;
    state.lastPolicy = policy;
    elements.policyStatus.textContent = policy.allowed ? policy.reason : policy.reason || "denied";
    elements.policyStatus.className = policy.allowed ? "allowed" : "denied";
    elements.snapshotOutput.textContent = JSON.stringify(policy, null, 2);
  } catch (error) {
    elements.policyStatus.textContent = "preflight_failed";
    elements.policyStatus.className = "denied";
    elements.snapshotOutput.textContent = String(error);
  }
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".pane").forEach((pane) => pane.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.pane}`).classList.add("active");
  });
});

elements.preflightForm.addEventListener("submit", preflight);
elements.refreshButton.addEventListener("click", refreshStatus);
refreshStatus();
