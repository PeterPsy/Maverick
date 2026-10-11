export function mountShell(connectorMode) {
  document.querySelector("#app").innerHTML = `<main>
    <header class="app-header">
      <span class="app-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18Z"/></svg></span>
      <div class="header-copy"><h1>Browser</h1><p>Your shared tabs and web research, in one place.</p></div>
      <a id="connectors-link" class="button secondary" target="_top">Open Connectors <span aria-hidden="true">↗</span></a>
    </header>
    <div class="metrics" aria-label="Browser overview">
      <div><span>Shared tabs</span><strong id="tab-count">—</strong><small>Connected to Chrome</small></div>
      <div><span>In progress</span><strong id="pending-count">—</strong><small>Queued or running observations</small></div>
      <div><span>Recent activity</span><strong id="activity-count">—</strong><small>Latest 30 operations</small></div>
    </div>
    <div class="workspace-toolbar">
      <nav aria-label="Browser sections">
        <button data-view="tabs" aria-current="page">Shared tabs</button>
        <button data-view="activity">Activity</button>
        <button data-view="lab">Browser Lab</button>
      </nav>
      <button id="refresh" class="secondary" aria-label="Refresh Browser">Refresh</button>
    </div>
    <p id="error" class="error" role="alert" hidden></p>
    <section id="tabs-view" aria-label="Shared tabs">
      <details id="setup" class="panel setup" ${connectorMode ? "open" : ""}>
        <summary><span><strong>${connectorMode ? "Connect your selected tab" : "Connect Chrome"}</strong><small>Start an agent tab or share a platform page</small></span><span class="chevron" aria-hidden="true">⌄</span></summary>
        <div class="setup-body">
          <p>A dedicated agent tab can navigate between Instagram, X, Reddit, Facebook, LinkedIn and YouTube. An existing shared tab can navigate throughout its selected platform. Sign in to the platforms in your usual Chrome profile.</p>
          <ol class="setup-steps">
            <li><strong>Install Companion 0.5.3</strong><p><a id="download" download="maverick-browser-companion.zip">Download the extension</a> and extract it. In <code>chrome://extensions</code>, enable Developer mode and choose Load unpacked. After an update, replace the extracted files and reload the extension.</p></li>
            <li><strong>Connect once from Companion</strong><p>Choose Open agent tab, then open Companion on that new tab and choose Connect agent tab. To share a platform page instead, open Companion on it and choose Share this tab. The Maverick address is already configured; allow Chrome access when asked.</p></li>
            <li><strong>Keep both tabs open</strong><p>Companion reuses an existing Maverick tab in the same Chrome profile and connects automatically after sign-in. The agent navigates the shared tab. Desktop apps and other browser profiles need a separate Chrome bridge window.</p></li>
          </ol>
          <details class="connection-settings"><summary>Using another Maverick installation?</summary><p>Set this address in Companion's Connection settings.</p><label for="url">Connector address</label>
          <div class="copy"><input id="url" readonly spellcheck="false"><button id="copy" class="secondary">Copy address</button></div></details>
          <div id="connector-actions" class="actions" ${connectorMode ? "" : "hidden"}><button id="connect" disabled>Connect selected tab</button><button id="stop" class="secondary" hidden>Stop sharing</button></div>
          <p id="status" class="status" role="status">${connectorMode ? "Checking for the tab shared with this window…" : "Installing Companion is the first step. Choose Open agent tab in Companion, or share an existing platform tab."}</p>
        </div>
      </details>
      <section class="panel"><div class="section-title"><div><h2>Shared tabs</h2><p>Delegate a dedicated tab or share an existing platform tab. Navigation, reading and media analysis are available; posting and form entry are not.</p></div><span class="badge">Read only</span></div>
        <div id="connections" class="records" aria-label="Chrome connections"><div class="empty">Loading shared tabs…</div></div>
      </section>
    </section>
    <section id="activity-view" class="panel" aria-label="Activity" hidden>
      <div class="section-title"><div><h2>Activity</h2><p>Track observations, cancel pending work and read results.</p></div></div>
      <div class="filters"><input id="search" type="search" aria-label="Search activity" placeholder="Search actions or shared tabs…"><select id="filter" aria-label="Filter activity"><option value="all">All activity</option><option value="active">In progress</option><option value="completed">Completed</option><option value="failed">Needs attention</option></select></div>
      <div id="operations" class="records" aria-label="Recent operations"></div>
      <p id="activity-note" class="section-note"></p>
    </section>
    <section id="lab-view" aria-label="Browser Lab" hidden>
      <section class="panel"><div class="section-title"><div><h2>Browser Lab</h2><p>Read public web pages in a temporary, isolated browser.</p></div><span id="lab-health" class="badge">Loading…</span></div>
        <form id="research"><label for="research-url">Public page URL</label><div class="copy"><input id="research-url" type="url" placeholder="https://example.com" required maxlength="4096"><button>Read page</button></div></form>
        <p id="research-status" class="status" role="status">The temporary session closes automatically after reading.</p>
      </section>
      <section class="panel"><div class="section-title"><div><h2>Lab sessions</h2><p>Temporary research and development sessions.</p></div></div><p id="lab-error" class="error" role="alert" hidden></p><div id="lab-sessions" class="records"></div></section>
    </section>
    <footer><span id="updated" role="status">Connecting to Browser…</span><p>Sharing ends when you stop it, close the tab or leave supported pages. Sign-in stays in Chrome.</p></footer>
  </main>`;
}
