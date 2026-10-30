// WebsitesPulse: an alphabetical website grid with hosting filters and inline details.

const WORD = {
  up: "Up",
  degraded: "Warning",
  down: "Error",
  unknown: "No data",
};
const CHECK_WORD = { ok: "OK", warn: "Warning", down: "Error" };
const CHECK_TAG = { ok: "up", warn: "degraded", down: "down" };
const FACTS = [
  ["host", "Hosted on"],
  ["account", "Account"],
  ["php_version", "PHP"],
  ["wordpress_version", "WordPress"],
  ["plugins_vulnerable", "Vulnerable plugins and themes"],
  ["last_backup_at", "Last backup"],
  ["visits_24h", "Visits (24 hours)"],
  ["bandwidth_bytes_24h", "Server bandwidth (bytes, 24 hours)"],
  ["cdn_bandwidth_bytes_24h", "CDN bandwidth (bytes, 24 hours)"],
  ["disk_bytes", "Disk usage (bytes)"],
  ["http_4xx_24h", "4xx responses (24 hours)"],
  ["http_5xx_24h", "5xx responses (24 hours)"],
  ["analytics_from", "Analytics from"],
  ["analytics_to", "Analytics to"],
  ["analytics_at", "Analytics collected"],
  ["http_status", "HTTP status"],
  ["response_ms", "Response time (ms)"],
];

const ui = {
  filter: "all",
  place: null,
  network: null,
  php: null,
  wordpress: null,
  query: "",
  picked: new URLSearchParams(location.hash.slice(1)).get("site"),
};
let data = null;

function readFilters() {
  const url = new URL(location.href);
  for (const [field, key] of [["place", "hosting"], ["network", "network"], ["php", "php"], ["wordpress", "wordpress"]])
    ui[field] = url.searchParams.get(key)?.slice(0, 200) || null;
  ui.query = url.searchParams.get("q")?.trim().toLowerCase().slice(0, 500) || "";
  const state = url.searchParams.get("status");
  ui.filter = ["up", "degraded", "down", "unknown"].includes(state) ? state : "all";
  ui.picked = url.searchParams.get("site") || new URLSearchParams(url.hash.slice(1)).get("site");
}
readFilters();

function websiteUrl() {
  const url = new URL(location.href);
  for (const [key, value] of [["hosting", ui.place], ["network", ui.network], ["php", ui.php], ["wordpress", ui.wordpress],
    ["status", ui.filter === "all" ? null : ui.filter], ["q", ui.query], ["site", ui.picked]]) {
    if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  }
  const legacy = new URLSearchParams(url.hash.slice(1));
  if (legacy.has("site")) { legacy.delete("site"); url.hash = legacy.toString(); }
  return url;
}
function writeFilters(replace = false) {
  const url = websiteUrl();
  if (url.href !== location.href) history[replace ? "replaceState" : "pushState"](null, "", url.href);
}
function hasFilters() {
  return Boolean(ui.place || ui.network || ui.php || ui.wordpress || ui.query || ui.filter !== "all");
}
function clearFilters() {
  Object.assign(ui, {place:null, network:null, php:null, wordpress:null, query:"", filter:"all", picked:null});
}
function websiteFacts(w) { return {...(w.hosting?.facts || {}), ...(w.facts || {})}; }
function renderDropdowns() {
  const configs = [["hosting", "place", "All hosting", w => w.group], ["network", "network", "All networks", w => w.network || "unknown"],
    ["php", "php", "All PHP versions", w => websiteFacts(w).php_version || "unknown"],
    ["wordpress", "wordpress", "All WordPress versions", w => websiteFacts(w).wordpress_version || "unknown"]];
  for (const [id, field, all, valueOf] of configs) {
    const select = document.getElementById(id);
    const values = new Map();
    for (const w of data.websites) {
      if (["php", "wordpress"].includes(id) && ((ui.place && w.group !== ui.place) || (ui.network && w.network !== ui.network))) continue;
      const value = valueOf(w);
      values.set(value, (values.get(value) || 0) + 1);
    }
    if (ui[field] && !values.has(ui[field])) values.set(ui[field], 0);
    const options = [["", all], ...[...values].sort(([a], [b]) => a.localeCompare(b, undefined, {numeric:true})).map(([value, count]) => {
      const label = id === "hosting" ? data.groups.find(g => g.id === value)?.name || value : value === "unknown" ? "Not reported" : value;
      return [value, `${label} · ${count}`];
    })];
    const signature = JSON.stringify(options);
    if (select.dataset.choices !== signature) {
      select.replaceChildren(...options.map(([value, label]) => { const option = el("option", null, label); option.value = value; return option; }));
      select.dataset.choices = signature;
    }
    select.value = ui[field] || "";
  }
}
let layoutFrame;
function scheduleLayout() {
  if (typeof requestAnimationFrame !== "function") return;
  cancelAnimationFrame(layoutFrame);
  layoutFrame = requestAnimationFrame(() => {
    const list = document.getElementById("groups");
    if (!list.clientWidth) return;
    const cards = [...list.children];
    for (const card of cards) { card.style.gridColumn = ""; card.style.gridRow = ""; }
    const columns = getComputedStyle(list).gridTemplateColumns.split(" ").length;
    const heights = Array(columns).fill(0);
    cards.forEach((card, index) => {
      const column = index % columns;
      const height = Math.ceil(card.getBoundingClientRect().height);
      card.style.gridColumn = card.className === "empty-state" ? "1 / -1" : String(column + 1);
      card.style.gridRow = `${heights[column] + 1} / span ${height}`;
      heights[column] += height + 12;
    });
    list.style.minHeight = "";
  });
}


function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function ago(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function fact(key, value) {
  if (value == null || value === "") return null;
  if (key === "last_backup_at")
    return `${new Date(value).toLocaleString()} (${ago(value)})`;
  return String(value);
}

function matches(w) {
  if (ui.place && w.group !== ui.place) return false;
  if (ui.network && (w.network || "unknown") !== ui.network) return false;
  if (ui.php && (websiteFacts(w).php_version || "unknown") !== ui.php) return false;
  if (ui.wordpress && (websiteFacts(w).wordpress_version || "unknown") !== ui.wordpress) return false;
  if (ui.filter !== "all" && w.state !== ui.filter) return false;
  if (!ui.query) return true;
  const f = websiteFacts(w);
  const hay =
    `${w.name} ${w.network || ""} ${w.hostname || ""} ${w.url || ""} ${w.owner || ""} ${f.php_version || ""} php${f.php_version || ""} ${f.wordpress_version || ""} ${f.account || ""}`.toLowerCase();
  return ui.query.split(/\s+/).every((q) => hay.includes(q));
}

function hostingName(w) {
  return data.groups.find((g) => g.id === w.group)?.name || w.facts?.host || "Host not recorded";
}

function visibleWebsites() {
  return data.websites.filter(matches).sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true }) ||
    a.id.localeCompare(b.id),
  );
}

function renderPicture() {
  const wrap = document.getElementById("picture");
  wrap.replaceChildren(...data.groups.filter((g) => g.websites).map((g) => {
    const b = el("button", "place", g.name);
    b.type = "button";
    b.setAttribute("aria-pressed", String(ui.place === g.id));
    b.title = `${g.counts.up} of ${g.websites} up`;
    b.append(el("span", "place-count", String(g.websites)));
    b.addEventListener("click", () => {
      ui.place = ui.place === g.id ? null : g.id;
      writeFilters();
      render();
    });
    return b;
  }));
  const networks = [...new Set(data.websites.map((w) => w.network).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  for (const network of networks) {
    const sites = data.websites.filter((w) => w.network === network);
    const b = el("button", "place", network);
    b.type = "button";
    b.setAttribute("aria-pressed", String(ui.network === network));
    b.title = `${sites.filter((w) => w.state === "up").length} of ${sites.length} up`;
    b.append(el("span", "place-count", String(sites.length)));
    b.addEventListener("click", () => {
      ui.network = ui.network === network ? null : network;
      writeFilters();
      render();
    });
    wrap.append(b);
  }
}

function renderDetails(w) {
  const box = el("section", "details");
  box.id = `details-${w.id}`;
  const dl = el("dl");
  const add = (label, value) => {
    if (value) dl.append(el("dt", null, label), el("dd", null, value));
  };
  add("Address", w.url || w.hostname);
  add("Owner", w.owner);
  add("Network", w.network);
  add("Hosting", hostingName(w));
  for (const [key, label] of FACTS) add(label, fact(key, (w.facts || {})[key]));
  add(
    "Last heard",
    w.lastCheck
      ? `${new Date(w.lastCheck).toLocaleString()} (${ago(w.lastCheck)})`
      : "Nothing yet",
  );
  box.append(dl);
  if (w.hosting) {
    box.append(el("h4", null, `Shared ${w.hosting.name} hosting`));
    const shared = el("dl");
    for (const [key, label] of FACTS) {
      const value = fact(key, w.hosting.facts?.[key]);
      if (value != null) shared.append(el("dt", null, label), el("dd", null, value));
    }
    box.append(shared);
    const parent = el("a", null, "View shared installation analytics");
    const parentUrl = websiteUrl();
    for (const key of ["hosting", "network", "php", "wordpress", "status", "q"]) parentUrl.searchParams.delete(key);
    parentUrl.searchParams.set("site", w.hosting.website_id);
    parent.href = parentUrl.href;
    box.append(parent);
    if (w.hosting.lastCheck) box.append(el("p", null, `Hosting reported ${ago(w.hosting.lastCheck)}`));
  }
  if (w.network && !w.hosting && w.facts?.analytics_at)
    box.append(el("p", null, `Analytics cover the whole ${w.network} network.`));
  if ((w.alerts || []).length) {
    box.append(el("h4", null, "Alerts"));
    const ul = el("ul");
    for (const a of w.alerts) {
      const li = el("li");
      li.append(
        el("span", `tag ${a.severity === "critical" ? "down" : "degraded"}`),
        el(
          "span",
          null,
          `${a.source}: ${a.text}${a.since ? ` · since ${ago(a.since)}` : ""}`,
        ),
      );
      ul.append(li);
    }
    box.append(ul);
  }
  if ((w.checks || []).length) {
    box.append(el("h4", null, "Checks"));
    const ul = el("ul");
    for (const c of w.checks) {
      const li = el("li");
      li.append(
        el("span", `tag ${CHECK_TAG[c.state]}`),
        el(
          "span",
          null,
          `${c.source} · ${CHECK_WORD[c.state]}${c.reason === "restricted" ? " · Access restricted" : c.reason === "rate-limited" ? " · Rate limited" : ""}${c.at ? ` · ${ago(c.at)}` : ""}`,
        ),
      );
      ul.append(li);
    }
    box.append(ul);
  }
  if (w.url) {
    const links = el("p", "link");
    const open = el("a", null, "Open the site");
    open.href = w.url;
    open.target = "_blank";
    open.rel = "noopener noreferrer";
    const share = el("a", null, "Link to this entry");
    const shareUrl = websiteUrl();
    shareUrl.searchParams.set("site", w.id);
    share.href = shareUrl.href;
    links.append(open, share);
    box.append(links);
  }
  return box;
}

function row(w) {
  const li = el("li", "website-card");
  const b = el("button", "row");
  b.type = "button";
  const open = ui.picked === w.id;
  b.setAttribute("aria-expanded", String(open));
  b.setAttribute("aria-controls", `details-${w.id}`);
  b.append(el("span", `tag ${w.state}`));
  b.lastChild.setAttribute("aria-label", WORD[w.state]);
  const who = el("span", "who");
  who.append(
    el("span", "name", w.name),
    el("span", "host", hostingName(w)),
  );
  if (w.network) who.append(el("span", "host network", w.network));
  const side = el("span", "side");
  const f = websiteFacts(w);
  const versions = [
    f.php_version && `PHP ${f.php_version}`,
    f.wordpress_version && `WP ${f.wordpress_version}`,
  ]
    .filter(Boolean)
    .join(" · ");
  if (versions) side.append(el("span", "versions", versions));
  if (w.facts?.http_status) side.append(el("span", null, `HTTP ${w.facts.http_status}`));
  if (w.hosting && versions) side.append(el("span", null, `Shared ${w.hosting.name} hosting`));
  if (w.facts?.visits_24h != null)
    side.append(el("span", null, `${w.facts.visits_24h.toLocaleString()} visits · 24 h`));
  side.append(el("span", "when", w.lastCheck ? ago(w.lastCheck) :
    w.network ? "No individual check received" : "No checks received"));
  b.append(who, el("span", "disclosure", open ? "−" : "+"), side);
  for (const a of (w.alerts || []).slice(0, 2))
    b.append(el("span", `alert ${a.severity}`, a.text));
  b.addEventListener("click", () => pick(open ? null : w.id));
  li.append(b);
  if (open) li.append(renderDetails(w));
  return li;
}

function renderGroups() {
  const wrap = document.getElementById("groups");
  const members = visibleWebsites();
  if (wrap.style && wrap.getBoundingClientRect) wrap.style.minHeight = `${wrap.getBoundingClientRect().height}px`;
  if (members.length) wrap.replaceChildren(...members.map(row));
  else wrap.replaceChildren(el("li", "empty-state", "No websites match these filters."));
  renderTotal(members);
  scheduleLayout();
}

function pick(id) {
  ui.picked = id;
  writeFilters();
  renderGroups();
}

function renderTotal(members = visibleWebsites()) {
  const total = document.getElementById("total");
  const count = members.length === data.websites.length
    ? `${data.websites.length} websites`
    : `${members.length} of ${data.websites.length} websites`;
  const up = members.filter((w) => w.state === "up").length;
  const unknown = members.filter((w) => w.state === "unknown").length;
  total.replaceChildren(el("b", null, count), document.createTextNode(` · ${up} up`));
  if (unknown) total.append(document.createTextNode(` · ${unknown} no data`));
}

function render() {
  if (!data) return;
  for (const b of document.querySelectorAll("#filter button"))
    b.setAttribute("aria-pressed", String(b.dataset.v === ui.filter));
  document.getElementById("sample").hidden = !data.sample;
  document.getElementById("search").value = ui.query;
  document.getElementById("clear-filters").hidden = !hasFilters();
  renderDropdowns();
  renderPicture();
  renderGroups();
}

document.getElementById("filter").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  ui.filter = ui.filter === b.dataset.v ? "all" : b.dataset.v;
  writeFilters();
  render();
});
document.getElementById("search").addEventListener("input", (e) => {
  ui.query = e.target.value.trim().toLowerCase();
  writeFilters(true);
  render();
});
for (const event of ["popstate", "hashchange"]) window.addEventListener(event, () => { readFilters(); if (data) render(); });
for (const [id, field] of [["hosting", "place"], ["network", "network"], ["php", "php"], ["wordpress", "wordpress"]])
  document.getElementById(id).addEventListener("change", e => { ui[field] = e.target.value || null; writeFilters(); render(); });
document.getElementById("clear-filters").addEventListener("click", () => { clearFilters(); writeFilters(); render(); });
document.getElementById("filter-link").append(Pulse.copyLink(() => websiteUrl().href, "filtered websites"));
new ResizeObserver(scheduleLayout).observe(document.getElementById("groups"));
document.fonts.ready.then(scheduleLayout);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && ui.picked) pick(null);
  if (
    e.key === "/" &&
    !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)
  ) {
    e.preventDefault();
    document.getElementById("search").focus();
  }
});

(async () => {
  await Pulse.shell({
    current: "websites",
    title: "Websites Status",
    context: "Websites, where they are hosted and how they answer",
    hideOverview: true,
  });
  Pulse.poll(async () => {
    const r = await fetch("api/status", { cache: "no-store" });
    if (!r.ok) throw new Error(`status ${r.status}`);
    data = await r.json();
    render();
    document.getElementById("updated").textContent =
      `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
  }, 30000);
})();
