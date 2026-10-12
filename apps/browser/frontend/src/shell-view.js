export function mountShell(connectorMode) {
  document.querySelector("#app").innerHTML = `<main>
    <header class="app-header">
      <span class="app-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18Z"/></svg></span>
      <div class="header-copy"><h1>Browser</h1><p>A Chrome tab for your agent.</p></div>
      <button id="show-setup" class="secondary">Set up extension</button>
    </header>
    <div class="workspace-toolbar">
      <nav aria-label="Browser sections">
        <button data-view="tabs" aria-current="page">Agent tab</button>
        <button data-view="activity">Activity</button>
      </nav>
      <button id="refresh" class="secondary" aria-label="Refresh Browser">Refresh</button>
    </div>
    <p id="error" class="error" role="alert" hidden></p>
    <section id="tabs-view" aria-label="Agent tab">
      <section class="panel agent-panel" aria-labelledby="agent-heading">
        <div class="section-title"><div><h2 id="agent-heading">Checking your agent tab…</h2><p id="agent-description">Connecting to Chrome.</p></div><span id="agent-state" class="badge">Checking</span></div>
        <div id="connections" class="records" aria-label="Agent connections"></div>
        <p class="section-note agent-capabilities">Navigate, read, scroll and analyze images, video and audio across Instagram, X, Reddit, Facebook, LinkedIn and YouTube.</p>
        <p id="pending-note" class="section-note" hidden></p>
      </section>
      <details id="setup" class="panel setup">
        <summary><span><strong>Set up your agent tab</strong><small>Install once, then connect from Chrome</small></span><span class="chevron" aria-hidden="true">⌄</span></summary>
        <div class="setup-body">
          <ol class="setup-steps">
            <li><strong>Install Companion 0.5.5</strong><p><a id="download" download="maverick-browser-companion.zip">Download the extension</a> and extract it. In <code>chrome://extensions</code>, enable Developer mode and choose Load unpacked. To update, replace the extracted files and reload the extension.</p></li>
            <li><strong>Open your agent tab</strong><p>Open Companion in Chrome and choose Open agent tab. On that tab, click Companion in the toolbar and choose Connect agent tab. Allow access if Chrome asks.</p></li>
            <li><strong>Ask Maverick</strong><p>Maverick connects automatically. Tell your agent what to research; it chooses the pages. Keep the agent tab and Maverick open in the same Chrome profile. Sign in to platforms directly in Chrome.</p></li>
          </ol>
          <details class="connection-settings"><summary>Using another Maverick installation?</summary><p>Set this address in Companion's Connection settings.</p><label for="url">Maverick address</label>
          <div class="copy"><input id="url" readonly spellcheck="false"><button id="copy" class="secondary">Copy address</button></div></details>
        </div>
      </details>
      <div id="connector-actions" class="connector-actions" hidden><button id="connect" disabled>Retry connection</button></div>
      <p id="status" class="status" role="status"></p>
      <details id="connection-history" class="panel history" hidden><summary>Previous connections</summary><div id="past-connections" class="records"></div></details>
    </section>
    <section id="activity-view" class="panel" aria-label="Activity" hidden>
      <div class="section-title"><div><h2>Agent activity</h2><p>Follow the agent's progress and view its results.</p></div></div>
      <div class="filters"><input id="search" type="search" aria-label="Search activity" placeholder="Search activity…"><select id="filter" aria-label="Filter activity"><option value="all">All activity</option><option value="active">In progress</option><option value="completed">Completed</option><option value="failed">Needs attention</option></select></div>
      <div id="operations" class="records" aria-label="Recent operations"></div>
      <p id="activity-note" class="section-note"></p>
    </section>
    <footer><span id="updated" role="status">Connecting to Browser…</span><p>Sign-in stays in Chrome. Posting, messages and form entry are not available.</p></footer>
  </main>`;
  document.querySelector("#setup").open = connectorMode;
}
