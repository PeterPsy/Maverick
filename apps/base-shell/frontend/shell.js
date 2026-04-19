const shell = document.getElementById("shell");
const appsApi = shell.dataset.appsApi || "/api/apps";
const appGrid = document.getElementById("appGrid");
const appGridPanel = document.getElementById("appGridPanel");
const appPanel = document.getElementById("appPanel");
const appFrame = document.getElementById("appFrame");
const pinnedApps = document.getElementById("pinnedApps");
const appsButton = document.getElementById("appsButton");
const backdrop = document.getElementById("backdrop");
const panelMinimize = document.getElementById("panelMinimize");
const panelPeek = document.getElementById("panelPeek");
const newChatButton = document.getElementById("newChatButton");

const preferredPinnedApps = [
  {
    app_id: "attachments",
    name: "Gallery",
    logo: {
      kind: "image",
      value:
        'data:image/svg+xml;utf8,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%2096%2096%22%3E%3Cdefs%3E%3ClinearGradient%20id=%22g%22%20x1=%220%22%20y1=%220%22%20x2=%221%22%20y2=%221%22%3E%3Cstop%20offset=%220%22%20stop-color=%22%23fb7185%22/%3E%3Cstop%20offset=%221%22%20stop-color=%22%23f59e0b%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width=%2296%22%20height=%2296%22%20rx=%2224%22%20fill=%22%2313111c%22/%3E%3Crect%20x=%2218%22%20y=%2218%22%20width=%2240%22%20height=%2250%22%20rx=%2210%22%20fill=%22%23f8fafc%22%20opacity=%22.98%22/%3E%3Crect%20x=%2234%22%20y=%2228%22%20width=%2244%22%20height=%2250%22%20rx=%2210%22%20fill=%22url(%23g)%22%20opacity=%22.96%22/%3E%3Ccircle%20cx=%2249%22%20cy=%2243%22%20r=%227%22%20fill=%22%23fff%22%20opacity=%22.95%22/%3E%3Cpath%20d=%22M40%2066%2051%2054l8%208%208-10%2011%2014%22%20stroke=%22%23fff7ed%22%20stroke-width=%226%22%20stroke-linecap=%22round%22%20stroke-linejoin=%22round%22%20fill=%22none%22/%3E%3C/svg%3E',
    },
  },
  {
    app_id: "app-studio",
    name: "App Studio",
    logo: {
      kind: "image",
      value:
        'data:image/svg+xml;utf8,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%2096%2096%22%3E%3Cdefs%3E%3ClinearGradient%20id=%22g%22%20x1=%220%22%20y1=%220%22%20x2=%221%22%20y2=%221%22%3E%3Cstop%20offset=%220%22%20stop-color=%22%235eead4%22/%3E%3Cstop%20offset=%221%22%20stop-color=%22%232563eb%22/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect%20width=%2296%22%20height=%2296%22%20rx=%2224%22%20fill=%22%2307111f%22/%3E%3Crect%20x=%2214%22%20y=%2218%22%20width=%2268%22%20height=%2250%22%20rx=%2214%22%20fill=%22url(%23g)%22%20opacity=%22.95%22/%3E%3Cpath%20d=%22M24%2032h48M24%2044h31M24%2056h24%22%20stroke=%22%23fff%22%20stroke-width=%226%22%20stroke-linecap=%22round%22%20opacity=%22.92%22/%3E%3Cpath%20d=%22M63%2064%2079%2080%22%20stroke=%22%23fef08a%22%20stroke-width=%228%22%20stroke-linecap=%22round%22/%3E%3Cpath%20d=%22m60%2078%207-18%2011-3-11-3-7-18-7%2018-11%203%2011%203z%22%20fill=%22%23fde68a%22/%3E%3C/svg%3E',
    },
  },
  {
    app_id: "checklists",
    name: "Checklists",
    logo: {
      kind: "image",
      value:
        'data:image/svg+xml;utf8,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%2096%2096%22%3E%3Crect%20width=%2296%22%20height=%2296%22%20rx=%2224%22%20fill=%22%23111827%22/%3E%3Crect%20x=%2218%22%20y=%2218%22%20width=%2260%22%20height=%2260%22%20rx=%2216%22%20fill=%22%23f8fafc%22/%3E%3Crect%20x=%2226%22%20y=%2228%22%20width=%2212%22%20height=%2212%22%20rx=%223%22%20fill=%22%2322c55e%22/%3E%3Cpath%20d=%22m29%2034%203%203%205-6%22%20stroke=%22%23fff%22%20stroke-width=%223%22%20stroke-linecap=%22round%22%20stroke-linejoin=%22round%22%20fill=%22none%22/%3E%3Crect%20x=%2226%22%20y=%2246%22%20width=%2212%22%20height=%2212%22%20rx=%223%22%20fill=%22%2360a5fa%22/%3E%3Cpath%20d=%22M46%2034h22M46%2052h22M26%2070h42%22%20stroke=%22%231f2937%22%20stroke-width=%226%22%20stroke-linecap=%22round%22%20opacity=%22.9%22/%3E%3Ccircle%20cx=%2274%22%20cy=%2272%22%20r=%2212%22%20fill=%22%23f59e0b%22/%3E%3Cpath%20d=%22m69%2072%204%204%208-9%22%20stroke=%22%23fff%22%20stroke-width=%224%22%20stroke-linecap=%22round%22%20stroke-linejoin=%22round%22%20fill=%22none%22/%3E%3C/svg%3E',
    },
  },
];

function setSidebar(open) {
  shell.classList.toggle("is-sidebar-open", open);
}

function getInitials(name) {
  return (name || "App")
    .replace(/[^A-Za-z0-9]+/g, " ")
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function findApp(apps, candidate) {
  const normalizedName = candidate.name.toLowerCase();
  return (
    apps.find((app) => app.app_id === candidate.app_id) ||
    apps.find((app) => String(app.name || "").toLowerCase() === normalizedName)
  );
}

function appLogo(app, fallback) {
  const logo = app.logo || fallback.logo;
  const badge = document.createElement("span");
  badge.className = `bs-app-logo--sidebar ${logo?.kind === "image" ? "is-image" : "is-glyph"}`;

  if (logo?.kind === "image" && logo.value) {
    const image = document.createElement("img");
    image.className = "bs-app-logo__image";
    image.alt = "";
    image.loading = "lazy";
    image.src = logo.value;
    badge.appendChild(image);
    return badge;
  }

  const glyph = document.createElement("span");
  glyph.className = "bs-app-logo__glyph";
  glyph.textContent = logo?.value || getInitials(app.name);
  badge.appendChild(glyph);
  return badge;
}

function setActiveButton(button) {
  for (const item of document.querySelectorAll(".bs-sidebar__nav-button")) {
    item.classList.toggle("is-active", item === button);
  }
}

function showApps() {
  appFrame.removeAttribute("src");
  appPanel.classList.remove("is-active");
  appGridPanel.classList.add("is-active");
  setActiveButton(appsButton);
}

function openApp(app, button) {
  if (!app.frontend_mount) return;
  appFrame.src = app.frontend_mount;
  appGridPanel.classList.remove("is-active");
  appPanel.classList.add("is-active");
  setActiveButton(button);
  setSidebar(false);
}

function navButton(app, fallback) {
  const button = document.createElement("button");
  button.className = "bs-sidebar__nav-button";
  button.type = "button";
  button.appendChild(document.createElement("span"));
  button.firstElementChild.className = "bs-sidebar__nav-leading";
  button.firstElementChild.appendChild(appLogo(app, fallback));

  const copy = document.createElement("span");
  copy.className = "bs-sidebar__nav-copy";
  const title = document.createElement("span");
  title.className = "bs-sidebar__nav-title";
  title.textContent = fallback.name;
  copy.appendChild(title);
  button.firstElementChild.appendChild(copy);

  button.addEventListener("click", () => openApp(app, button));
  return button;
}

function renderPinnedApps(apps) {
  pinnedApps.replaceChildren();
  for (const fallback of preferredPinnedApps) {
    const app = findApp(apps, fallback) || {
      app_id: fallback.app_id,
      name: fallback.name,
      frontend_mount: "",
      logo: fallback.logo,
    };
    pinnedApps.appendChild(navButton(app, fallback));
  }
}

function renderAppGrid(apps) {
  appGrid.replaceChildren();
  const visibleApps = apps.filter((app) => app.app_id !== "base-shell");
  if (!visibleApps.length) {
    const empty = document.createElement("p");
    empty.className = "bs-empty-state";
    empty.textContent = "Nessuna app installata.";
    appGrid.appendChild(empty);
    return;
  }

  for (const app of visibleApps) {
    const card = document.createElement("button");
    card.className = "bs-app-card";
    card.type = "button";
    card.innerHTML = `
      <span class="bs-app-card__body">
        <span class="bs-app-card__title"></span>
        <span class="bs-app-card__description"></span>
      </span>
    `;
    card.querySelector(".bs-app-card__title").textContent = app.name || app.app_id;
    card.querySelector(".bs-app-card__description").textContent =
      app.description || "App montata dal manifest della shell.";
    card.addEventListener("click", () => openApp(app, card));
    appGrid.appendChild(card);
  }
}

async function loadApps() {
  const response = await fetch(appsApi);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json();
  const apps = payload.items || [];
  renderPinnedApps(apps);
  renderAppGrid(apps);
  showApps();
}

appsButton.addEventListener("click", showApps);
backdrop.addEventListener("click", () => setSidebar(false));
panelMinimize.addEventListener("click", () => setSidebar(false));
panelPeek.addEventListener("click", () => setSidebar(true));
newChatButton.addEventListener("click", () => {
  const chat = [...document.querySelectorAll(".bs-sidebar__nav-button")].find((button) => button.textContent.includes("Chat"));
  if (chat) chat.click();
});

loadApps().catch((error) => {
  appGrid.replaceChildren();
  const empty = document.createElement("p");
  empty.className = "bs-empty-state";
  empty.textContent = `Failed to load apps: ${error.message}`;
  appGrid.appendChild(empty);
});
