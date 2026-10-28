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
];

const ui = {
  filter: "all",
  place: null,
  query: "",
  picked: new URLSearchParams(location.hash.slice(1)).get("site"),
};
let data = null;

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
  if (ui.filter !== "all" && w.state !== ui.filter) return false;
  if (!ui.query) return true;
  const f = w.facts || {};
  const hay =
    `${w.name} ${w.hostname || ""} ${w.url || ""} ${w.owner || ""} ${f.php_version || ""} php${f.php_version || ""} ${f.wordpress_version || ""} ${f.account || ""}`.toLowerCase();
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
      render();
    });
    return b;
  }));
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
  add("Hosting", hostingName(w));
  for (const [key, label] of FACTS) add(label, fact(key, (w.facts || {})[key]));
  add(
    "Last heard",
    w.lastCheck
      ? `${new Date(w.lastCheck).toLocaleString()} (${ago(w.lastCheck)})`
      : "Nothing yet",
  );
  box.append(dl);
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
          `${c.source} · ${CHECK_WORD[c.state]}${c.at ? ` · ${ago(c.at)}` : ""}`,
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
    share.href = `#site=${encodeURIComponent(w.id)}`;
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
  const side = el("span", "side");
  const f = w.facts || {};
  const versions = [
    f.php_version && `PHP ${f.php_version}`,
    f.wordpress_version && `WP ${f.wordpress_version}`,
  ]
    .filter(Boolean)
    .join(" · ");
  if (versions) side.append(el("span", "versions", versions));
  side.append(el("span", "when", ago(w.lastCheck)));
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
  if (members.length) wrap.replaceChildren(...members.map(row));
  else wrap.replaceChildren(el("li", "empty-state", "No websites match these filters."));
  renderTotal(members);
}

function pick(id) {
  ui.picked = id;
  history.replaceState(
    null,
    "",
    id
      ? `#site=${encodeURIComponent(id)}`
      : location.pathname + location.search,
  );
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
  renderPicture();
  renderGroups();
}

document.getElementById("filter").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  ui.filter = ui.filter === b.dataset.v ? "all" : b.dataset.v;
  render();
});
document.getElementById("search").addEventListener("input", (e) => {
  ui.query = e.target.value.trim().toLowerCase();
  renderGroups();
});
window.addEventListener("hashchange", () => {
  ui.picked = new URLSearchParams(location.hash.slice(1)).get("site");
  if (data) renderGroups();
});
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
