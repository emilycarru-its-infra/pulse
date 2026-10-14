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
function renderBrowse() {
  const query = ui.search.value.trim().toLocaleLowerCase();
  const apps = catalog.filter((a) => a.name.toLocaleLowerCase().includes(query) && (!ui.category.value || a.category === ui.category.value) && (!ui.platform.value || a.platforms.includes(ui.platform.value)));
  ui["result-count"].textContent = `${apps.length} software titles`;
  ui.empty.hidden = apps.length > 0;
  const focus = document.activeElement?.closest(".software-row")?.dataset.id;
  ui["software-list"].replaceChildren(...apps.map((app) => {
    const a = document.createElement("a"); a.href = `#${app.id}`; a.className = "software-row"; a.dataset.id = app.id;
    a.append(icon(app));
    const name = document.createElement("div"); name.className = "software-name";
    name.append(text("h2", app.name), text("span", app.category, "category")); a.append(name);
    a.append(text("span", app.platforms.map(platformName).join(" · "), "platforms"));
    a.append(text("span", app.locations.length ? `${app.locations.length} location${app.locations.length === 1 ? "" : "s"}` : "No recent reports", "location-total"));
    const arrow = text("span", "→", "row-arrow"); arrow.setAttribute("aria-hidden", "true"); a.append(arrow);
    return a;
  }));
  if (focus) [...ui["software-list"].children].find((a) => a.dataset.id === focus)?.focus();
}
function renderLocations(app) {
  const version = ui.version.value;
  const locations = app.locations.map((location) => {
    const counts = version ? location.versions.find((v) => v.version === version) : location;
    return counts ? { ...location, ...counts } : null;
  }).filter(Boolean);
  ui["location-count"].textContent = `${locations.length} location${locations.length === 1 ? "" : "s"} with recent installation reports`;
  ui["no-locations"].hidden = locations.length > 0;
  ui.locations.replaceChildren(...locations.map((location) => {
    const row = document.createElement("article"); row.className = "location-row";
    const name = document.createElement("div"); name.append(text("h4", location.name));
    name.append(text("p", [location.room && `Room ${location.room}`, location.platforms.map(platformName).join(" · ")].filter(Boolean).join(" · ")));
    row.append(name);
    const count = document.createElement("div"); count.className = "location-capacity";
    count.append(text("strong", `${location.computers} computer${location.computers === 1 ? "" : "s"}`), text("span", `${location.available} free now`)); row.append(count);
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
