// ServersPulse: where the servers run (one card per place), then every server grouped by the
// service it carries or by where it runs, and a details panel for the one picked.

const WORD = { up: "Up", degraded: "Degraded", down: "Down", stopped: "Stopped", unknown: "No data" };
const LEVEL = { ok: "Normal", warn: "Degraded", bad: "Down", idle: "No data" };
const RANK = { down: 0, degraded: 1, unknown: 2, up: 3, stopped: 4 };
const LEVEL_RANK = { bad: 0, warn: 1, idle: 2, ok: 3 };
const HOT = 90;

const ui = { view: "service", filter: "all", place: null, query: "", picked: null };
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
  const parts = [["up", "up"], ["degraded", "degraded"], ["down", "down"], ["unknown", "no data"], ["stopped", "stopped"]]
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
  if (ui.filter === "attention" && !["down", "degraded", "unknown"].includes(s.state)) return false;
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
    const v = m ? m[k] : null;
    const b = el("span", `bar${v >= HOT ? " hot" : ""}`);
    b.title = v == null ? `${label}: no data` : `${label} ${Math.round(v)}%`;
    b.innerHTML = `${label}<i><b style="width:${v ?? 0}%"></b></i>`;
    wrap.append(b);
  }
  return wrap;
}

function row(s) {
  const li = el("li");
  const b = el("button", "row");
  b.type = "button";
  b.dataset.id = s.id;
  if (s.id === ui.picked) b.setAttribute("aria-current", "true");
  b.setAttribute("aria-label", `${s.name}, ${WORD[s.state]}`);
  const tag = el("span", `tag ${s.state}`);
  tag.title = WORD[s.state];
  const who = el("span", "who");
  who.append(el("span", "name", s.name));
  const sub = el("span", "sub");
  sub.innerHTML = `<code></code> · `;
  sub.querySelector("code").textContent = s.id;
  sub.append(s.role || "");
  who.append(sub);
  const side = el("span", "side");
  side.append(bars(s.metrics), el("span", "when", s.state === "stopped" ? "stopped" : Pulse.ago(s.lastCheck)));
  b.append(tag, who, side);
  for (const a of s.alerts || []) b.append(el("span", `alert ${a.severity}`, `${a.source}: ${a.text}`));
  b.addEventListener("click", () => pick(s.id));
  li.append(b);
  return li;
}

function groups() {
  const servers = data.servers.filter(matches);
  const sort = (list) => list.sort((a, b) => RANK[a.state] - RANK[b.state] || a.name.localeCompare(b.name));
  const out = [];
  if (ui.view === "service") {
    for (const svc of data.services) {
      const members = servers.filter((s) => (s.services || []).includes(svc.id));
      if (members.length) out.push({ title: svc.name, kicker: `${svc.servers} server${svc.servers > 1 ? "s" : ""}`, level: svc.level, servers: sort(members) });
    }
    const loose = servers.filter((s) => !(s.services || []).length);
    if (loose.length) out.push({ title: "No service recorded", kicker: "Not yet linked to a service in the inventory", level: worst(loose), servers: sort(loose) });
  } else {
    for (const l of data.locations) {
      const members = servers.filter((s) => s.location === l.id);
      if (members.length) out.push({ title: l.name, kicker: l.detail || "", level: l.level, servers: sort(members) });
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
    wrap.replaceChildren(el("p", "card empty-state", ui.filter === "attention" ? "Nothing needs attention." : "No server matches."));
    return;
  }
  wrap.replaceChildren(...list.map((g) => {
    const card = el("section", "card group");
    card.innerHTML = `<div class="head"><div><h3></h3><p class="kicker"></p></div></div>`;
    card.querySelector("h3").textContent = g.title;
    card.querySelector(".kicker").textContent = g.kicker;
    card.querySelector(".head").append(chip(g.level));
    const ul = el("ul", "rows");
    ul.append(...g.servers.map(row));
    card.append(ul);
    return card;
  }));
}

function renderDrawer() {
  const drawer = document.getElementById("drawer");
  const s = data.servers.find((x) => x.id === ui.picked);
  if (!s) { drawer.hidden = true; return; }
  const place = data.locations.find((l) => l.id === s.location) || {};
  drawer.hidden = false;
  drawer.innerHTML = `<div class="head"><div><p class="kicker"></p><h3></h3></div><button type="button" class="close">Close</button></div>
    <p class="state-line"><span class="tag ${s.state}"></span><span></span></p><dl></dl>`;
  drawer.querySelector(".kicker").textContent = `${place.name || ""} · ${s.env || ""}`;
  drawer.querySelector("h3").textContent = s.name;
  drawer.querySelector(".state-line span:last-child").textContent =
    s.state === "stopped" ? "Stopped on purpose" : `${WORD[s.state]}${s.uptimeDays ? ` · up ${s.uptimeDays} days` : ""}`;
  const dl = drawer.querySelector("dl");
  const facts = [["Name", s.id], ["Role", s.role], ["OS", s.os], ["Runs on", [place.name, s.site].filter(Boolean).join(" · ")],
    ["Host", s.host], ["Services", (s.services || []).map((id) => data.serviceNames[id] || id).join(", ")]];
  for (const [k, v] of facts) {
    if (!v) continue;
    dl.append(el("dt", null, k));
    const dd = el("dd");
    if (k === "Name") dd.append(el("code", null, v)); else dd.textContent = v;
    dl.append(dd);
  }
  if (s.metrics) {
    drawer.append(el("h4", null, "Now"));
    for (const [k, label] of [["cpu", "CPU"], ["mem", "Memory"], ["disk", "Disk"]]) {
      const v = s.metrics[k];
      const m = el("div", `metric${v >= HOT ? " hot" : ""}`);
      m.innerHTML = `<span>${label}</span><i><b style="width:${v}%"></b></i><span>${Math.round(v)}%</span>`;
      drawer.append(m);
    }
  }
  if ((s.alerts || []).length) {
    drawer.append(el("h4", null, "Alerts"));
    const ul = el("ul", "list alerts");
    for (const a of s.alerts) {
      const li = el("li", a.severity);
      li.innerHTML = `<b></b><span class="muted"></span>`;
      li.querySelector("b").textContent = a.text;
      li.querySelector(".muted").textContent = `${a.source} · since ${new Date(a.since).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
      ul.append(li);
    }
    drawer.append(ul);
  }
  if ((s.checks || []).length) {
    drawer.append(el("h4", null, "Sources"));
    const ul = el("ul", "list");
    for (const c of s.checks) {
      const li = el("li");
      li.innerHTML = `<span></span><span class="muted"></span>`;
      li.firstChild.textContent = c.source;
      li.lastChild.textContent = `${c.state === "ok" ? "OK" : c.state === "warn" ? "Warning" : "Failing"} · ${Pulse.ago(c.at)}`;
      ul.append(li);
    }
    drawer.append(ul);
  }
  drawer.querySelector(".close").addEventListener("click", () => pick(null));
}

function pick(id) {
  ui.picked = ui.picked === id ? null : id;
  history.replaceState(null, "", ui.picked ? `#server=${encodeURIComponent(ui.picked)}` : location.pathname);
  renderGroups();
  renderDrawer();
  if (ui.picked) document.getElementById("drawer").querySelector(".close")?.focus({ preventScroll: true });
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
  renderDrawer();
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
  await Pulse.shell({ current: "servers", title: "Server Status", context: "Servers and services, on premises and in the cloud" });
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
