// ServersPulse: where the servers run (one card per place), then every server grouped by the
// service it carries or by where it runs, and inline details for the selected entry.

const WORD = { up: "Up", degraded: "Warning", down: "Error", stopped: "Stopped", unknown: "No data" };
const LEVEL = { ok: "Normal", warn: "Warning", bad: "Error", idle: "No data" };
const RANK = { down: 0, degraded: 1, unknown: 2, up: 3, stopped: 4 };
const LEVEL_RANK = { bad: 0, warn: 1, idle: 2, ok: 3 };
function usage(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return { value: null, level: "unavailable" };
  const v = Math.max(0, Math.min(100, value));
  return { value: v, level: v >= 90 ? "critical" : v >= 80 ? "warning" : "normal" };
}

const ui = { view: "service", filter: "all", place: null, query: "", picked: null, pickedGroup: null };
let data = null;

function remember() {
  try { localStorage.setItem("servers.view", ui.view); } catch { /* private window */ }
}
try { ui.view = localStorage.getItem("servers.view") || ui.view; } catch { /* private window */ }
ui.picked = new URLSearchParams(location.hash.slice(1)).get("server");

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function chip(level) {
  return el("span", `chip ${level}`, LEVEL[level]);
}

function countsLine(c) {
  const parts = [["up", "up"], ["degraded", "warning"], ["down", "error"], ["unknown", "no data"], ["stopped", "stopped"]]
    .filter(([k]) => c[k]).map(([k, w]) => `<b>${c[k]}</b> ${w}`);
  return parts.join(" · ");
}

function meter(c) {
  const m = el("div", "meter");
  const total = Object.values(c).reduce((a, b) => a + b, 0) || 1;
  m.setAttribute("role", "img");
  m.setAttribute("aria-label", Object.entries(c).filter(([, v]) => v).map(([k, v]) => `${v} ${WORD[k].toLowerCase()}`).join(", "));
  for (const k of ["up", "degraded", "down", "unknown", "stopped"]) {
    if (!c[k]) continue;
    const s = el("span", k);
    s.style.width = `${(100 * c[k]) / total}%`;
    m.append(s);
  }
  return m;
}

function matches(s) {
  if (ui.place && s.location !== ui.place) return false;
  if (ui.filter !== "all" && s.state !== ui.filter) return false;
  if (!ui.query) return true;
  const services = (s.services || []).map((id) => data.serviceNames[id] || id).join(" ");
  const hay = `${s.name} ${s.id} ${s.alias || ""} ${s.role || ""} ${s.os || ""} ${services}`.toLowerCase();
  return ui.query.split(/\s+/).every((w) => hay.includes(w));
}

function renderPicture() {
  const wrap = document.getElementById("picture");
  wrap.replaceChildren(...data.locations.filter((l) => l.servers).map((l) => {
    const b = el("button", "place");
    b.type = "button";
    b.setAttribute("aria-pressed", String(ui.place === l.id));
    b.title = ui.place === l.id ? "Show every location" : `Show only ${l.name}`;
    b.innerHTML = `<div class="head"><div><h3></h3><p class="detail"></p></div></div>
      <p class="big"></p><p class="counts"></p><p class="sources"></p>`;
    b.querySelector("h3").textContent = l.name;
    b.querySelector(".detail").textContent = l.detail || "";
    b.querySelector(".head").append(chip(l.level));
    const running = l.servers - l.counts.stopped;
    b.querySelector(".big").innerHTML = `${l.counts.up}<small>of ${running} healthy</small>`;
    b.querySelector(".counts").innerHTML = countsLine(l.counts) + (l.alerts ? ` · <b>${l.alerts}</b> alert${l.alerts > 1 ? "s" : ""}` : "");
    b.querySelector(".counts").before(meter(l.counts));
    const src = b.querySelector(".sources");
    src.append("Monitored by ");
    (l.sources || []).forEach((s, i) => { if (i) src.append(" + "); src.append(el("b", null, s)); });
    b.addEventListener("click", () => { ui.place = ui.place === l.id ? null : l.id; render(); });
    return b;
  }));
}

function bars(m) {
  const wrap = el("span", "bars");
  for (const [k, label] of [["cpu", "CPU"], ["mem", "Mem"], ["disk", "Disk"]]) {
    const { value: v, level } = usage(m?.[k]);
    const b = el("span", `bar usage-${level}`);
    b.title = v == null ? `${label}: no data` : `${label} ${Math.round(v)}%`;
    b.innerHTML = `${label}<i><b style="width:${v ?? 0}%"></b></i>`;
    wrap.append(b);
  }
  return wrap;
}

function row(s, groupKey, regionId) {
  const li = el("li");
  const b = el("button", "row");
  b.type = "button";
  b.dataset.id = s.id;
  const expanded = s.id === ui.picked && groupKey === ui.pickedGroup;
  b.setAttribute("aria-expanded", String(expanded));
  b.setAttribute("aria-controls", regionId);
  b.setAttribute("aria-label", `${s.name}, ${WORD[s.state]}`);
  const tag = el("span", `tag ${s.state}`);
  tag.title = WORD[s.state];
  tag.setAttribute("aria-hidden", "true");
  const who = el("span", "who");
  who.append(el("span", "name", s.name));
  const identity = el("code", "hostname", s.id);
  who.append(identity);
  if (s.role) who.append(el("span", "server-role", s.role));
  const side = el("span", "side");
  side.append(bars(s.metrics), el("span", "when", s.state === "stopped" ? "stopped" : Pulse.ago(s.lastCheck)));
  b.append(tag, who, side);
  const disclosure = el("span", "disclosure", expanded ? "−" : "+");
  disclosure.setAttribute("aria-hidden", "true");
  b.append(disclosure);
  for (const a of s.alerts || []) b.append(el("span", `alert ${a.severity}`, `${a.source}: ${a.text}`));
  b.addEventListener("click", () => pick(s.id, groupKey, b));
  const details = expanded ? renderDetails(s) : el("section", "server-details");
  details.id = regionId;
  details.hidden = !expanded;
  details.setAttribute("aria-label", `${s.name} details`);
  li.append(b, details);
  return li;
}

function groups() {
  const servers = data.servers.filter(matches);
  const sort = (list) => list.sort((a, b) => RANK[a.state] - RANK[b.state] || a.name.localeCompare(b.name));
  const out = [];
  if (ui.view === "service") {
    for (const svc of data.services) {
      const members = servers.filter((s) => (s.services || []).includes(svc.id));
      if (members.length) out.push({ key: `service:${svc.id}`, title: svc.name, kicker: `${svc.servers} server${svc.servers > 1 ? "s" : ""}`, level: svc.level, servers: sort(members) });
    }
    const loose = servers.filter((s) => !(s.services || []).length);
    if (loose.length) out.push({ key: "unassigned", title: "No service recorded", kicker: "Not yet linked to a service in the inventory", level: worst(loose), servers: sort(loose) });
  } else {
    for (const l of data.locations) {
      const members = servers.filter((s) => s.location === l.id);
      if (members.length) out.push({ key: `location:${l.id}`, title: l.name, kicker: l.detail || "", level: l.level, servers: sort(members) });
    }
  }
  return out.sort((a, b) => LEVEL_RANK[a.level] - LEVEL_RANK[b.level] || a.title.localeCompare(b.title));
}

function worst(list) {
  const r = Math.min(...list.map((s) => RANK[s.state]));
  return r === 0 ? "bad" : r === 1 ? "warn" : r === 2 ? "idle" : "ok";
}

function renderGroups() {
  const wrap = document.getElementById("groups");
  const list = groups();
  if (!list.length) {
    wrap.replaceChildren(el("p", "card empty-state", ui.filter === "all" ? "No server matches." : `No servers with ${WORD[ui.filter].toLowerCase()}.`));
    return;
  }
  if (ui.picked && !list.some((g) => g.key === ui.pickedGroup && g.servers.some((s) => s.id === ui.picked))) {
    ui.pickedGroup = list.find((g) => g.servers.some((s) => s.id === ui.picked))?.key || null;
  }
  wrap.replaceChildren(...list.map((g, groupIndex) => {
    const card = el("section", "card group");
    card.innerHTML = `<div class="head"><div><h3></h3><p class="kicker"></p></div></div>`;
    card.querySelector("h3").textContent = g.title;
    card.querySelector(".kicker").textContent = g.kicker;
    card.querySelector(".head").append(chip(g.level));
    const ul = el("ul", "rows");
    ul.append(...g.servers.map((s, rowIndex) => row(s, g.key, `server-details-${groupIndex}-${rowIndex}`)));
    card.append(ul);
    return card;
  }));
}

function renderDetails(s) {
  const panel = el("section", "server-details");
  const place = data.locations.find((l) => l.id === s.location) || {};
  panel.innerHTML = `<div class="head"><p class="kicker"></p></div>
    <p class="state-line"></p><dl></dl>`;
  panel.querySelector(".kicker").textContent = `${place.name || ""} · ${s.env || ""}`;
  panel.querySelector(".state-line").textContent =
    s.state === "stopped" ? "Stopped on purpose" : `${WORD[s.state]}${s.uptimeDays ? ` · ${s.uptimeDays} days uptime` : ""}`;
  const dl = panel.querySelector("dl");
  const facts = [["Hostname", s.id], ["Role", s.role], ["OS", s.os], ["Runs on", [place.name, s.site].filter(Boolean).join(" · ")],
    ["Host", s.host], ["Services", (s.services || []).map((id) => data.serviceNames[id] || id).join(", ")]];
  for (const [k, v] of facts) {
    if (!v) continue;
    dl.append(el("dt", null, k));
    const dd = el("dd");
    if (k === "Hostname") dd.append(el("code", null, v)); else dd.textContent = v;
    dl.append(dd);
  }
  if (s.metrics) {
    panel.append(el("h4", null, "Resource usage"));
    for (const [k, label] of [["cpu", "CPU"], ["mem", "Memory"], ["disk", "Disk"]]) {
      const { value: v, level } = usage(s.metrics[k]);
      if (v == null) continue;
      const m = el("div", `metric usage-${level}`);
      m.innerHTML = `<span>${label}</span><i><b style="width:${v}%"></b></i><span>${Math.round(v)}%</span>`;
      panel.append(m);
    }
  }
  if ((s.alerts || []).length) {
    panel.append(el("h4", null, "Alerts"));
    const ul = el("ul", "list alerts");
    for (const a of s.alerts) {
      const li = el("li", a.severity);
      li.innerHTML = `<b></b><span class="muted"></span>`;
      li.querySelector("b").textContent = a.text;
      li.querySelector(".muted").textContent = `${a.source} · since ${new Date(a.since).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
      ul.append(li);
    }
    panel.append(ul);
  }
  if ((s.checks || []).length) {
    panel.append(el("h4", null, "Sources"));
    const ul = el("ul", "list");
    for (const c of s.checks) {
      const li = el("li");
      const level = c.state === "ok" ? "ok" : c.state === "warn" ? "warn" : c.state === "down" ? "bad" : "idle";
      const name = el("span", "source-name", c.source);
      const status = el("span", `source-severity ${level}`, { ok: "OK", warn: "Warning", bad: "Error", idle: "No data" }[level]);
      li.className = "source-check";
      li.append(status, name, el("span", "source-age", Pulse.ago(c.at)));
      ul.append(li);
    }
    panel.append(ul);
  }
  return panel;
}

function pick(id, groupKey = ui.pickedGroup, trigger = null) {
  const close = ui.picked === id && ui.pickedGroup === groupKey;
  ui.picked = close ? null : id;
  ui.pickedGroup = ui.picked ? groupKey : null;
  history.replaceState(null, "", ui.picked ? `#server=${encodeURIComponent(ui.picked)}` : location.pathname);
  renderGroups();
  if (trigger) document.querySelectorAll(".row").forEach((button) => {
    if (button.dataset.id === trigger.dataset.id && button.getAttribute("aria-controls") === trigger.getAttribute("aria-controls")) button.focus({ preventScroll: true });
  });
}

function renderTotal() {
  const running = data.servers.filter((s) => s.state !== "stopped");
  const up = running.filter((s) => s.state === "up").length;
  const alerts = data.servers.reduce((n, s) => n + (s.alerts || []).length, 0);
  document.getElementById("total").innerHTML = `<b>${up}</b> of ${running.length} healthy` + (alerts ? ` · <b>${alerts}</b> alert${alerts > 1 ? "s" : ""}` : "");
}

function render() {
  if (!data) return;
  for (const g of ["view", "filter"]) {
    for (const b of document.querySelectorAll(`#${g} button`)) b.setAttribute("aria-pressed", String(b.dataset.v === ui[g]));
  }
  document.getElementById("sample").hidden = !data.sample;
  renderTotal();
  renderPicture();
  renderGroups();
}

for (const g of ["view", "filter"]) {
  document.getElementById(g).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    ui[g] = b.dataset.v;
    if (g === "view") remember();
    render();
  });
}
document.getElementById("search").addEventListener("input", (e) => { ui.query = e.target.value.trim().toLowerCase(); renderGroups(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && ui.picked) pick(null);
  if (e.key === "/" && document.activeElement?.tagName !== "INPUT") { e.preventDefault(); document.getElementById("search").focus(); }
});

(async () => {
  await Pulse.shell({ current: "servers", title: "Server Status", context: "Servers and services, on premises and in the cloud", hideOverview: true });
  Pulse.poll(async () => {
    const r = await fetch("api/status", { cache: "no-store" });
    if (!r.ok) throw new Error(`status ${r.status}`);
    data = await r.json();
    data.serviceNames = Object.fromEntries(data.services.map((s) => [s.id, s.name]));
    render();
    document.getElementById("updated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
  }, 30000);
})();

Pulse.masonry(document.getElementById("groups"));
