const ui = Object.fromEntries(["notice", "browse", "view", "search", "category", "platform", "result-count", "software-list", "empty", "detail", "detail-icon", "detail-share", "detail-category", "software-title", "detail-platforms", "location-count", "version", "locations", "no-locations"].map((id) => [id, document.getElementById(id)]));
let catalog = [], selected = "", loaded = false, platformFilter = "", view = "software";
const openApps = new Set();
const appVersionFilters = new Map();
const appSlug = (app) => app.name.normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const matchesApp = (app, key) => app.id === key || appSlug(app) === key;
let locationFilter = "";
const browseValues = () => ({ view, category: ui.category.value, platform: platformFilter, q: ui.search.value, location: locationFilter });
const softwareURL = (extra = {}) => Pulse.linkURL({ ...browseValues(), ...extra });
const appUrl = (app, version = "", extra = {}) => softwareURL({ app: appSlug(app), version, ...extra });
function recordView(push = false) {
  const app = catalog.find((a) => matchesApp(a, selected));
  const open = catalog.find((a) => openApps.has(a.id));
  const values = { ...browseValues(), app: app ? appSlug(app) : "", open: !app && open ? appSlug(open) : "",
    version: app ? ui.version.value : open ? appVersionFilters.get(open.id) : "" };
  const url = Pulse.linkURL(values);
  if (url !== location.href) history[push ? "pushState" : "replaceState"](null, "", url);
}
function readView() {
  const params = new URLSearchParams(location.search);
  selected = params.get("app") || (!location.hash.includes("=") ? location.hash.slice(1) : "");
  view = params.get("view") === "locations" ? "locations" : "software";
  platformFilter = ["mac", "windows"].includes(params.get("platform")) ? params.get("platform") : "";
  locationFilter = params.get("location") || "";
  ui.search.value = params.get("q") || "";
  ui.category.dataset.requested = params.get("category") || "";
  ui.version.value = "";
  openApps.clear(); appVersionFilters.clear();
  const app = catalog.find((a) => matchesApp(a, params.get("open")));
  if (app) { openApps.add(app.id); appVersionFilters.set(app.id, params.get("version") || ""); }
  for (const option of ui.view.querySelectorAll("button")) option.setAttribute("aria-pressed", String(option.dataset.v === view));
  for (const option of ui.platform.querySelectorAll("button")) option.setAttribute("aria-pressed", String(option.dataset.v === platformFilter));
  ui.search.placeholder = view === "software" ? "Search software" : "Search rooms or software";
  ui.search.setAttribute("aria-label", ui.search.placeholder);
}
const copyButton = (app) => Pulse.copyLink(() => appUrl(app, appVersionFilters.get(app.id)), app.name);
function locationLink(location, app = null, version = "") {
  const params = { view: "locations", location: location.id, app: "", open: "", version: "" };
  return app ? appUrl(app, version, { location: location.id }) : softwareURL(params);
}
function roomLinks(group, app = null, version = "") {
  const heading = document.createElement("div"); heading.className = "room-links";
  const locations = group.members.slice().sort((a, b) => (a.room || a.name).localeCompare(b.room || b.name, undefined, { numeric: true }));
  for (const item of locations) {
    const scope = document.createElement("span"); scope.className = "share-scope share-heading";
    const link = text("a", item.room || item.name, "room-number"); link.href = locationLink(item, app, version);
    scope.append(link, Pulse.copyLink(() => link.href, item.room || item.name)); heading.append(scope);
  }
  return heading;
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
function platformBadges(platforms) {
  const badges = document.createElement("div"); badges.className = "platform-badges";
  if (platformFilter) return document.createDocumentFragment();
  const paths = {'mac': 'M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z', 'windows': 'M3 3h8v8H3V3zm10 0h8v8h-8V3zM3 13h8v8H3v-8zm10 0h8v8h-8v-8z'};
  for (const platform of [...platforms].sort()) {
    if (!paths[platform]) continue;
    const badge = document.createElement("span"); badge.className = "platform-badge";
    badge.title = platformName(platform); badge.setAttribute("role", "img"); badge.setAttribute("aria-label", platformName(platform));
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "currentColor"); svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", paths[platform]);
    svg.append(path); badge.append(svg); badges.append(badge);
  }
  return badges;
}
function groupedLocations(app, version = "") {
  const groups = new Map();
  for (const location of app.locations) {
    if (locationFilter && location.id !== locationFilter) continue;
    if (platformFilter && !location.platforms.includes(platformFilter)) continue;
    const counts = version ? location.versions.find((v) => v.version === version) : location;
    if (!counts || (platformFilter && !counts.platforms.includes(platformFilter))) continue;
    const key = location.name.trim().toLocaleLowerCase();
    if (!groups.has(key)) groups.set(key, { name: location.name, rooms: new Set(), platforms: new Set(), versions: new Set(), members: [] });
    const group = groups.get(key);
    group.members.push(location);
    for (const item of location.versions || []) if (!version || item.version === version) group.versions.add(item.version);
    if (location.room) group.rooms.add(location.room);
    for (const platform of counts.platforms) group.platforms.add(platform);
  }
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name));
}
function holdLayoutHeight() {
  const list = ui["software-list"];
  list.style.minHeight = `${Math.max(list.getBoundingClientRect().height, parseFloat(list.style.minHeight) || 0)}px`;
}
let layoutFrame;
function scheduleLayout() {
  cancelAnimationFrame(layoutFrame);
  layoutFrame = requestAnimationFrame(() => {
    const list = ui["software-list"];
    if (!list.clientWidth) return;
    holdLayoutHeight();
    // Old explicit positions create implicit tracks after a narrower resize. Clear them
    // before reading the responsive CSS column count.
    for (const card of list.children) {
      card.style.gridColumn = "";
      card.style.gridRow = "";
    }
    const columns = getComputedStyle(list).gridTemplateColumns.split(" ").length;
    const heights = Array(columns).fill(0);
    [...list.children].forEach((card, index) => {
      const heading = card.querySelector("h2");
      if (view === "software") {
        heading.style.fontSize = "16px";
        if (heading.scrollWidth > heading.clientWidth) heading.style.fontSize = `${16 * heading.clientWidth / heading.scrollWidth}px`;
      }
      const column = view === "locations" ? heights.indexOf(Math.min(...heights)) : index % columns;
      const height = Math.ceil(card.getBoundingClientRect().height);
      card.style.gridColumn = String(column + 1);
      card.style.gridRow = `${heights[column] + 1} / span ${height}`;
      heights[column] += height + (view === "locations" ? 20 : 16);
    });
    list.style.minHeight = "";
  });
}
const cardObserver = new ResizeObserver(scheduleLayout);
new ResizeObserver(scheduleLayout).observe(ui["software-list"]);
document.fonts.ready.then(scheduleLayout);
function renderLocationBrowse(query) {
  const groups = new Map();
  for (const app of catalog) {
    if (ui.category.value && app.category !== ui.category.value) continue;
    for (const location of app.locations) {
      if (locationFilter && location.id !== locationFilter) continue;
      if (platformFilter && !location.platforms.includes(platformFilter)) continue;
      const key = location.id;
      if (!groups.has(key)) groups.set(key, { ...location, apps: [], platforms: new Set() });
      const group = groups.get(key);
      group.apps.push(app);
      location.platforms.forEach((p) => group.platforms.add(p));
    }
  }
  const locations = [...groups.values()].filter((group) =>
    [group.name, group.room, ...group.apps.map((app) => app.name)].join(" ").toLocaleLowerCase().includes(query)
  ).sort((a, b) => (a.room || a.name).localeCompare(b.room || b.name, undefined, { numeric: true }));
  ui["result-count"].textContent = `${locations.length} locations`;
  ui.empty.textContent = "No locations match your search.";
  ui.empty.hidden = locations.length > 0;
  ui["software-list"].replaceChildren(...locations.map((group) => {
    const card = document.createElement("article"); card.className = "location-card share-scope";
    const header = document.createElement("header");
    const heading = document.createElement("div"); heading.className = "share-heading share-scope";
    const title = text("h2", "", "room-number"), permalink = text("a", group.room || group.name); permalink.href = locationLink(group); title.append(permalink);
    heading.append(title, Pulse.copyLink(() => locationLink(group), group.room || group.name)); header.append(heading);
    if (group.room) header.append(text("p", group.name, "room-name"));
    header.append(platformBadges(group.platforms));
    card.append(header);
    const apps = document.createElement("div"); apps.className = "location-software";
    for (const app of group.apps) {
      const link = document.createElement("a"); link.href = appUrl(app, "", { location: group.id });
      link.append(icon(app, 32), text("span", app.name)); apps.append(link);
    }
    card.append(apps); return card;
  }));
}
function collapseAppsExcept(keep) {
  openApps.clear();
  for (const card of ui["software-list"].querySelectorAll(".software-card[open]")) {
    if (card === keep) openApps.add(card.dataset.id);
    else card.open = false;
  }
}
document.addEventListener("click", (event) => { if (!event.target.closest(".copy-link")) collapseAppsExcept(event.target.closest(".software-card")); });
function syncLinks() {
  document.querySelector(".back").href = softwareURL({ app: "", open: "", version: "" });
  const clear = document.querySelector(".clear-location");
  if (clear) { clear.href = softwareURL({ location: "", app: "", open: "" }); clear.hidden = !locationFilter; }
}
function renderBrowse() {
  holdLayoutHeight();
  syncLinks();
  const query = ui.search.value.trim().toLocaleLowerCase();
  cardObserver.disconnect();
  ui["software-list"].className = view === "software" ? "software-list" : "location-catalog";
  if (view === "locations") {
    renderLocationBrowse(query);
    for (const card of ui["software-list"].children) cardObserver.observe(card);
    scheduleLayout();
    return;
  }
  ui.empty.textContent = "No software matches your search.";
  const apps = catalog.filter((a) => a.name.toLocaleLowerCase().includes(query) && (!ui.category.value || a.category === ui.category.value) && (!platformFilter || a.platforms.includes(platformFilter)) && (!locationFilter || a.locations.some((location) => location.id === locationFilter && (!platformFilter || location.platforms.includes(platformFilter)))));
  ui["result-count"].textContent = `${apps.length} software titles`;
  ui.empty.hidden = apps.length > 0;
  const focused = document.activeElement?.closest(".software-card");
  const focusId = focused?.dataset.id, focusAction = document.activeElement?.dataset.action;
  ui["software-list"].replaceChildren(...apps.map((app) => {
    const card = document.createElement("details"); card.className = "software-card share-scope"; card.dataset.id = app.id;
    card.open = openApps.has(app.id);
    card.addEventListener("toggle", () => { if (card.isConnected) { if (card.open) collapseAppsExcept(card); else openApps.delete(app.id); scheduleLayout(); recordView(); } });
    const summary = document.createElement("summary");
    summary.append(icon(app, 64));
    const name = document.createElement("div"); name.className = "software-name";
    name.append(text("h2", app.name), text("span", app.category, "category")); summary.append(name);
    summary.append(copyButton(app));
    summary.append(platformBadges(app.platforms));
    const locations = groupedLocations(app);
    summary.append(text("span", locations.length ? `${locations.length} location${locations.length === 1 ? "" : "s"}` : "No recent reports", "location-total"));
    card.append(summary);
    const panel = document.createElement("div"); panel.className = "app-locations";
    const selectedVersion = appVersionFilters.get(app.id) || "";
    const version = app.versions?.includes(selectedVersion) ? selectedVersion : "";
    if (app.versions?.length) {
      const label = text("label", "Version", "app-version-filter");
      const select = document.createElement("select");
      select.setAttribute("aria-label", `Version for ${app.name}`); select.dataset.action = "version";
      select.append(new Option("All versions", ""), ...app.versions.map((v) => new Option(v, v)));
      select.value = version;
      select.addEventListener("change", () => { appVersionFilters.set(app.id, select.value); renderBrowse(); recordView(); });
      label.append(select); panel.append(label);
    }
    const filteredLocations = groupedLocations(app, version);
    if (!filteredLocations.length) panel.append(text("p", "No recent installation reports."));
    for (const location of filteredLocations.slice(0, 4)) {
      const item = document.createElement("div"); item.className = "compact-location";

      const rooms = [...location.rooms].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
      item.append(roomLinks(location, app, version));
      item.append(text("small", location.name));
      if (location.versions.size) item.append(text("span", `Versions: ${[...location.versions].join(" · ")}`, "location-versions"));
      panel.append(item);
    }
    const link = text("a", filteredLocations.length > 4 ? `All ${filteredLocations.length} locations →` : "App link →", "app-link");
    link.href = appUrl(app, version); link.dataset.action = "link";
    const actions = document.createElement("div"); actions.className = "app-actions";
    actions.append(link); panel.append(actions); card.append(panel);
    return card;
  }));
  for (const card of ui["software-list"].children) cardObserver.observe(card);
  scheduleLayout();
  if (focusId) {
    const card = [...ui["software-list"].children].find((a) => a.dataset.id === focusId);
    (focusAction ? card?.querySelector(`[data-action="${focusAction}"]`) : card?.querySelector("summary"))?.focus({ preventScroll: true });
  }
}
function renderLocations(app) {
  const locations = groupedLocations(app, ui.version.value);
  ui["location-count"].textContent = `${locations.length} location${locations.length === 1 ? "" : "s"}`;
  ui["no-locations"].hidden = locations.length > 0;
  ui.locations.replaceChildren(...locations.map((location) => {
    const row = document.createElement("article"); row.className = "location-row";

    const rooms = [...location.rooms].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    row.append(roomLinks(location, app, ui.version.value));
    if (rooms.length) row.append(text("p", location.name, "room-name"));
    row.append(platformBadges(location.platforms));
    return row;
  }));
}
function renderDetail(focus = false) {
  syncLinks();
  const app = catalog.find((a) => matchesApp(a, selected));
  if (!app) { ui.detail.hidden = true; ui.browse.hidden = false; return; }
  ui.browse.hidden = true; ui.detail.hidden = false;
  ui["detail-icon"].replaceChildren(icon(app, 72));
  ui["software-title"].textContent = app.name;
  ui["detail-category"].textContent = app.category;
  ui["detail-platforms"].textContent = app.platforms.map(platformName).join(" · ");
  const previous = new URLSearchParams(location.search).get("version") || "";
  ui.version.replaceChildren(new Option("All versions", ""), ...app.versions.map((v) => new Option(v, v)));
  ui.version.value = app.versions.includes(previous) ? previous : "";
  renderLocations(app);
  ui["detail-share"].replaceChildren(Pulse.copyLink(() => appUrl(app, ui.version.value), app.name));
  if (focus) ui["software-title"].focus();
}
for (const name of ["search", "category"]) ui[name].addEventListener(name === "search" ? "input" : "change", () => { renderBrowse(); recordView(name !== "search"); });
ui.view.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-v]");
  if (!button) return;
  view = button.dataset.v;
  for (const option of ui.view.querySelectorAll("button")) option.setAttribute("aria-pressed", String(option.dataset.v === view));
  ui.search.placeholder = view === "software" ? "Search software" : "Search rooms or software";
  ui.search.setAttribute("aria-label", ui.search.placeholder);
  renderBrowse(); recordView(true);
});
ui.platform.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-v]");
  if (!button) return;
  platformFilter = platformFilter === button.dataset.v ? "" : button.dataset.v;
  for (const option of ui.platform.querySelectorAll("button")) option.setAttribute("aria-pressed", String(option.dataset.v === platformFilter));
  renderBrowse(); recordView(true);
});
ui.version.addEventListener("change", () => { const app = catalog.find((a) => matchesApp(a, selected)); if (app) { renderLocations(app); recordView(); } });
(async () => {
  await Pulse.shell({ current: "software", compact: true, title: "Software Catalog", context: "Explore campus software and find where it’s available" });
  readView();
  const toolbar = document.querySelector(".catalog-toolbar"); toolbar.classList.add("share-scope"); toolbar.append(Pulse.copyLink(() => location.href, "this view"));
  const clear = text("a", "All locations", "clear-location"); clear.href = softwareURL({ location: "", app: "", open: "" }); clear.hidden = !locationFilter; toolbar.append(clear);
  document.querySelector(".back").href = softwareURL({ app: "", open: "", version: "" });
  Pulse.poll(async () => {
    try {
      const response = await fetch("api/status");
      if (!response.ok) throw new Error("Software locations are temporarily unavailable. Please try again shortly.");
      const data = await response.json();
      catalog = data.software;
      const category = ui.category.dataset.requested ?? ui.category.value;
      ui.category.replaceChildren(new Option("All categories", ""), ...[...new Set(catalog.map((a) => a.category))].sort().map((c) => new Option(c, c)));
      ui.category.value = category; delete ui.category.dataset.requested;
      if (!loaded) { const open = new URLSearchParams(location.search).get("open"); const app = catalog.find((a) => matchesApp(a, open)); if (app) { openApps.add(app.id); appVersionFilters.set(app.id, new URLSearchParams(location.search).get("version") || ""); } }
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

window.addEventListener("popstate", () => { readView(); ui.category.value = ui.category.dataset.requested; delete ui.category.dataset.requested; if (selected) renderDetail(); else { ui.detail.hidden = true; ui.browse.hidden = false; renderBrowse(); } });
