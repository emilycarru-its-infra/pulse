const ui = Object.fromEntries(["notice", "browse", "search", "category", "platform", "result-count", "software-list", "empty", "detail", "detail-icon", "detail-category", "software-title", "detail-platforms", "location-count", "version", "locations", "no-locations"].map((id) => [id, document.getElementById(id)]));
let catalog = [], selected = "", loaded = false;
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
  const apps = catalog.filter((a) => a.name.toLocaleLowerCase().includes(query) && (!ui.category.value || a.category === ui.category.value) && (!ui.platform.value || a.platforms.includes(ui.platform.value)));
  ui["result-count"].textContent = `${apps.length} software titles`;
  ui.empty.hidden = apps.length > 0;
  const focus = document.activeElement?.closest(".software-card")?.dataset.id;
  ui["software-list"].replaceChildren(...apps.map((app) => {
    const a = document.createElement("a"); a.href = `#${app.id}`; a.className = "software-card"; a.dataset.id = app.id;
    a.append(icon(app, 64));
    const name = document.createElement("div"); name.className = "software-name";
    name.append(text("h2", app.name), text("span", app.category, "category")); a.append(name);
    a.append(text("span", app.platforms.map(platformName).join(" · "), "platforms"));
    const locations = groupedLocations(app).length;
    a.append(text("span", locations ? `${locations} location${locations === 1 ? "" : "s"}` : "No recent reports", "location-total"));
    return a;
  }));
  if (focus) [...ui["software-list"].children].find((a) => a.dataset.id === focus)?.focus();
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
  const app = catalog.find((a) => a.id === selected);
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
function navigate() {
  selected = location.hash.slice(1);
  ui.version.value = "";
  renderDetail(true);
  if (!selected) { renderBrowse(); ui.search.focus(); }
}
window.addEventListener("hashchange", navigate);
for (const name of ["search", "category", "platform"]) ui[name].addEventListener(name === "search" ? "input" : "change", renderBrowse);
ui.version.addEventListener("change", () => { const app = catalog.find((a) => a.id === selected); if (app) renderLocations(app); });
(async () => {
  await Pulse.shell({ current: "software", title: "Software", context: "Explore campus software and find where it’s available" });
  selected = location.hash.slice(1);
  Pulse.poll(async () => {
    try {
      const response = await fetch("api/status");
      if (!response.ok) throw new Error("Software locations are temporarily unavailable. Please try again shortly.");
      const data = await response.json();
      catalog = data.software;
      const category = ui.category.value;
      ui.category.replaceChildren(new Option("All categories", ""), ...[...new Set(catalog.map((a) => a.category))].sort().map((c) => new Option(c, c)));
      ui.category.value = category;
      ui.notice.textContent = "Browse the campus software collection. Choose a title to see its locations.";
      ui.browse.hidden = !!selected; ui.detail.hidden = !selected;
      if (selected) renderDetail(!loaded); else renderBrowse();
      loaded = true;
    } catch (error) {
      ui.notice.textContent = error.message;
      ui.browse.hidden = true; ui.detail.hidden = true;
    }
  }, 30000);
})();
