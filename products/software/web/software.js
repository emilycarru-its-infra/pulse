const ui = Object.fromEntries(["notice", "browse", "search", "category", "platform", "result-count", "software-list", "empty", "detail", "detail-icon", "detail-category", "software-title", "detail-platforms", "location-count", "version", "locations", "no-locations"].map((id) => [id, document.getElementById(id)]));
let catalog = [], selected = "", loaded = false, platformFilter = "";
const openApps = new Set();
const appSlug = (app) => app.name.normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const matchesApp = (app, key) => app.id === key || appSlug(app) === key;
const appUrl = (app) => { const url = new URL(location.pathname, location.origin); url.searchParams.set("app", appSlug(app)); return url.href; };
function copyButton(app) {
  const button = text("button", "Copy link", "copy-link"); button.type = "button"; button.dataset.action = "copy";
  button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(appUrl(app)); button.textContent = "Copied"; }
    catch { button.textContent = "Use app link"; }
  });
  return button;
}
const platformName = (p) => p === "mac" ? "Mac" : p === "windows" ? "Windows" : p;
const text = (tag, value, cls) => { const n = document.createElement(tag); n.textContent = value; if (cls) n.className = cls; return n; };
function icon(app, size = 48) {
  if (app.icon && /^software-icons\/[a-f0-9]+\.(png|jpg|jpeg|webp)$/i.test(app.icon)) {
    const img = document.createElement("img"); img.src = app.icon; img.alt = ""; img.width = size; img.height = size;
    img.addEventListener("error", () => img.replaceWith(text("span", app.name.slice(0, 1), "icon-fallback")), { once: true });
    return img;
  }
  return text("span", app.name.slice(0, 1), "icon-fallback");
}
function groupedLocations(app, version = "") {
  const groups = new Map();
  for (const location of app.locations) {
    const counts = version ? location.versions.find((v) => v.version === version) : location;
    if (!counts) continue;
    const key = location.name.trim().toLocaleLowerCase();
    if (!groups.has(key)) groups.set(key, { name: location.name, rooms: new Set(), platforms: new Set() });
    const group = groups.get(key);
    if (location.room) group.rooms.add(location.room);
    for (const platform of counts.platforms) group.platforms.add(platform);
  }
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name));
}
function renderBrowse() {
  const query = ui.search.value.trim().toLocaleLowerCase();
  const apps = catalog.filter((a) => a.name.toLocaleLowerCase().includes(query) && (!ui.category.value || a.category === ui.category.value) && (!platformFilter || a.platforms.includes(platformFilter)));
  ui["result-count"].textContent = `${apps.length} software titles`;
  ui.empty.hidden = apps.length > 0;
  const focused = document.activeElement?.closest(".software-card");
  const focusId = focused?.dataset.id, focusAction = document.activeElement?.dataset.action;
  ui["software-list"].replaceChildren(...apps.map((app) => {
    const card = document.createElement("details"); card.className = "software-card"; card.dataset.id = app.id;
    card.open = openApps.has(app.id);
    card.addEventListener("toggle", () => { if (card.isConnected) { if (card.open) openApps.add(app.id); else openApps.delete(app.id); } });
    const summary = document.createElement("summary");
    summary.append(icon(app, 64));
    const name = document.createElement("div"); name.className = "software-name";
    name.append(text("h2", app.name), text("span", app.category, "category")); summary.append(name);
    summary.append(text("span", app.platforms.map(platformName).join(" · "), "platforms"));
    const locations = groupedLocations(app);
    summary.append(text("span", locations.length ? `${locations.length} location${locations.length === 1 ? "" : "s"}` : "No recent reports", "location-total"));
    card.append(summary);
    const panel = document.createElement("div"); panel.className = "app-locations";
    if (!locations.length) panel.append(text("p", "No recent installation reports."));
    for (const location of locations.slice(0, 4)) {
      const item = document.createElement("div"); item.className = "compact-location";
      item.append(text("strong", location.name));
      const rooms = [...location.rooms].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
      if (rooms.length) item.append(text("small", rooms.join(" · ")));
      panel.append(item);
    }
    const link = text("a", locations.length > 4 ? `All ${locations.length} locations →` : "App link →", "app-link");
    link.href = appUrl(app); link.dataset.action = "link";
    const actions = document.createElement("div"); actions.className = "app-actions";
    actions.append(link, copyButton(app)); panel.append(actions); card.append(panel);
    return card;
  }));
  if (focusId) {
    const card = [...ui["software-list"].children].find((a) => a.dataset.id === focusId);
    (focusAction ? card?.querySelector(`[data-action="${focusAction}"]`) : card?.querySelector("summary"))?.focus();
  }
}
function renderLocations(app) {
  const locations = groupedLocations(app, ui.version.value);
  ui["location-count"].textContent = `${locations.length} location${locations.length === 1 ? "" : "s"}`;
  ui["no-locations"].hidden = locations.length > 0;
  ui.locations.replaceChildren(...locations.map((location) => {
    const row = document.createElement("article"); row.className = "location-row";
    row.append(text("h4", location.name));
    const rooms = [...location.rooms].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    if (rooms.length) row.append(text("p", `${rooms.length === 1 ? "Room" : "Rooms"} ${rooms.join(" · ")}`, "location-rooms"));
    row.append(text("span", [...location.platforms].sort().map(platformName).join(" · "), "location-platforms"));
    return row;
  }));
}
function renderDetail(focus = false) {
  const app = catalog.find((a) => matchesApp(a, selected));
  if (!app) { ui.detail.hidden = true; ui.browse.hidden = false; return; }
  ui.browse.hidden = true; ui.detail.hidden = false;
  ui["detail-icon"].replaceChildren(icon(app, 72));
  ui["software-title"].textContent = app.name;
  ui["detail-category"].textContent = app.category;
  ui["detail-platforms"].textContent = app.platforms.map(platformName).join(" · ");
  const previous = ui.version.value;
  ui.version.replaceChildren(new Option("All versions", ""), ...app.versions.map((v) => new Option(v, v)));
  ui.version.value = app.versions.includes(previous) ? previous : "";
  renderLocations(app);
  if (focus) ui["software-title"].focus();
}
for (const name of ["search", "category"]) ui[name].addEventListener(name === "search" ? "input" : "change", renderBrowse);
ui.platform.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-v]");
  if (!button) return;
  platformFilter = platformFilter === button.dataset.v ? "" : button.dataset.v;
  for (const option of ui.platform.querySelectorAll("button")) option.setAttribute("aria-pressed", String(option.dataset.v === platformFilter));
  renderBrowse();
});
ui.version.addEventListener("change", () => { const app = catalog.find((a) => matchesApp(a, selected)); if (app) renderLocations(app); });
(async () => {
  await Pulse.shell({ current: "software", title: "Software", context: "Explore campus software and find where it’s available" });
  selected = new URLSearchParams(location.search).get("app") || location.hash.slice(1);
  document.querySelector(".back").href = location.pathname;
  Pulse.poll(async () => {
    try {
      const response = await fetch("api/status");
      if (!response.ok) throw new Error("Software locations are temporarily unavailable. Please try again shortly.");
      const data = await response.json();
      catalog = data.software;
      const category = ui.category.value;
      ui.category.replaceChildren(new Option("All categories", ""), ...[...new Set(catalog.map((a) => a.category))].sort().map((c) => new Option(c, c)));
      ui.category.value = category;
      ui.notice.textContent = "";
      ui.notice.hidden = true;
      ui.browse.hidden = !!selected; ui.detail.hidden = !selected;
      if (selected) renderDetail(!loaded); else renderBrowse();
      loaded = true;
    } catch (error) {
      ui.notice.hidden = false;
      ui.notice.textContent = error.message;
      ui.browse.hidden = true; ui.detail.hidden = true;
    }
  }, 30000);
})();
