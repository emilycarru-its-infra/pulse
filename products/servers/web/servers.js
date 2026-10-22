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

const ui = { view: "location", filter: "all", place: null, query: "", picked: null, pickedGroup: null, runtime: null, binaryVersion: null, binaryOpen: {}, compareClosed: new Set() };
let data = null;

function remember() {
  try { localStorage.setItem("servers.groupBy", ui.view); } catch { /* private window */ }
}
try { ui.view = localStorage.getItem("servers.groupBy") || ui.view; } catch { /* private window */ }
function readBinaryUrl() {
  const params = new URL(location.href).searchParams;
  ui.runtime = params.get("binary")?.trim().slice(0, 100) || null;
  ui.binaryVersion = ui.runtime ? params.get("version")?.trim().slice(0, 200) || null : null;
  ui.picked = params.get("server") || new URLSearchParams(location.hash.slice(1)).get("server");
  ui.pickedGroup = null;
}
readBinaryUrl();

// Compare mode: a binary link with no single server opens every matching server inline, showing only
// that binary, so versions can be read side by side. Each server can still be collapsed on its own.
function comparing() {
  return Boolean(ui.runtime && !ui.picked);
}

function binaryUrl(binary = ui.runtime, version = ui.binaryVersion, server = ui.picked) {
  const url = new URL(location.href);
  for (const [key, value] of [["binary", binary], ["version", binary ? version : null], ["server", server]]) {
    if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  }
  const legacy = new URLSearchParams(url.hash.slice(1));
  if (legacy.has("server")) { legacy.delete("server"); url.hash = legacy.toString(); }
  return url;
}

function writeBinaryUrl() {
  const url = binaryUrl();
  if (url.href !== location.href) history.pushState(null, "", url);
}
window.addEventListener("popstate", () => {
  readBinaryUrl();
  if (data) render();
});

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

function runtimeVersion(component) {
  const raw = component.version || "unknown";
  if (["running_binary_file_metadata", "installed_binary_file_metadata"].includes(component.evidence_kind)) {
    if (["PowerShell", ".NET host"].includes(component.name)) return raw.match(/^\d+(?:\.\d+){1,3}/)?.[0] || raw;
    if (component.name === "OpenSSH") return raw.match(/OpenSSH_([\w.-]+)/)?.[1] || raw;
  }
  return raw;
}

function runtimeLabel(component) {
  return `${component.name} ${runtimeVersion(component)}`;
}

function groupedRuntimes(components) {
  const groups = new Map();
  for (const c of components || []) {
    const key = JSON.stringify([c.name, c.version, c.executable, c.scope, c.container_id,
      c.container_name, c.running, c.evidence_kind, c.package_name, c.package_version]);
    if (!groups.has(key)) groups.set(key, { ...c, services: new Set(), records: new Set(), process_count: 0 });
    const row = groups.get(key);
    if (c.service) row.services.add(c.service);
    const signature = JSON.stringify(c);
    if (!row.records.has(signature)) row.process_count += c.process_count || 0;
    row.records.add(signature);
  }
  return [...groups.values()].map(({ services, records, ...c }) => ({ ...c, service: [...services].sort().join(", ") }));
}

function matches(s) {
  if (ui.runtime && !(s.runtimeInventory?.freshness === "fresh" && (s.runtimeInventory.components || []).some((c) => c.name === ui.runtime && (!ui.binaryVersion || runtimeVersion(c) === ui.binaryVersion)))) return false;
  if (ui.place && s.location !== ui.place) return false;
  if (ui.filter !== "all" && s.state !== ui.filter) return false;
  if (!ui.query) return true;
  const services = (s.services || []).map((id) => data.serviceNames[id] || id).join(" ");
  const runtimeText = (s.runtimeInventory?.components || []).map((c) => `${c.name} ${c.version || ""} ${c.package_name || ""} ${c.package_version || ""} ${c.service || ""} ${c.container_name || ""}`).join(" ");
  const hay = `${runtimeText} ${s.name} ${s.id} ${s.alias || ""} ${s.role || ""} ${s.os || ""} ${services}`.toLowerCase();
  return ui.query.split(/\s+/).every((w) => hay.includes(w));
}

function renderPicture() {
  const wrap = document.getElementById("picture");
  const byLocation = ui.view === "location";
  wrap.classList.toggle("by-location", byLocation);
  if (byLocation && ui.picked) {
    const selected = data.servers.find((s) => s.id === ui.picked);
    ui.pickedGroup = selected ? `location:${selected.location}` : null;
  }
  wrap.replaceChildren(...data.locations.filter((l) => l.servers).map((l, locationIndex) => {
    const b = el(byLocation ? "div" : "button", "place");
    if (!byLocation) {
      b.type = "button";
      b.setAttribute("aria-pressed", String(ui.place === l.id));
      b.title = ui.place === l.id ? "Show every location" : `Show only ${l.name}`;
    }
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
    if (!byLocation) {
      b.addEventListener("click", () => { ui.place = ui.place === l.id ? null : l.id; render(); });
      return b;
    }
    const card = el("section", "location-card");
    card.append(b);
    const members = data.servers.filter((s) => s.location === l.id && matches(s))
      .sort((a, b) => RANK[a.state] - RANK[b.state] || a.name.localeCompare(b.name));
    if (members.length) {
      const list = el("ul", "rows location-rows");
      list.append(...members.map((s, index) => row(s, `location:${l.id}`, `location-details-${locationIndex}-${index}`)));
      card.append(list);
    } else card.append(el("p", "location-empty", "No servers match the current filters."));
    return card;
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
  const compare = comparing();
  const expanded = compare ? !ui.compareClosed.has(s.id) : s.id === ui.picked && groupKey === ui.pickedGroup;
  li.classList.toggle("server-focus", expanded && !compare);
  li.classList.toggle("compare-open", expanded && compare);
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
  const inventory = s.runtimeInventory;
  if (inventory?.components?.length) {
    const labels = [...new Set(inventory.components.filter((c) => !ui.runtime || c.name === ui.runtime).map((c) => `${runtimeLabel(c)} · ${c.running ? "Running" : "Inactive"}`))];
    who.append(el("span", `runtime-tags ${inventory.freshness !== "fresh" ? "stale" : ""}`, `${inventory.freshness !== "fresh" ? "Last observed: " : ""}${labels.join(" · ")}`));
  }
  const side = el("span", "side");
  side.append(bars(s.metrics), el("span", "when", s.state === "stopped" ? "stopped" : Pulse.ago(s.lastCheck)));
  b.append(tag, who, side);
  const disclosure = el("span", "disclosure");
  disclosure.setAttribute("aria-hidden", "true");
  b.append(disclosure);
  for (const a of s.alerts || []) b.append(el("span", `alert ${a.severity}`, `${a.source}: ${a.text}`));
  b.addEventListener("click", () => compare ? toggleCompare(s.id, b) : pick(s.id, groupKey, b));
  const details = !expanded ? el("section", "server-details") : compare ? renderCompare(s, groupKey) : renderDetails(s);
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
    for (const group of data.serviceGroups || []) {
      const members = servers.filter((s) => (s.service_group || "").trim() === group.name);
      if (members.length) out.push({ key: `service:${group.name}`, title: group.name, kicker: `${group.servers} server${group.servers > 1 ? "s" : ""}`, level: group.level, servers: sort(members) });
    }
    const loose = servers.filter((s) => !(s.service_group || "").trim());
    if (loose.length) out.push({ key: "unassigned", title: "No service recorded", kicker: "No service group assigned in the inventory", level: worst(loose), servers: sort(loose) });
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
  wrap.parentElement.hidden = ui.view === "location";
  if (ui.view === "location") { wrap.replaceChildren(); return; }
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
  panel.append(runtimeDetails(s.runtimeInventory, s.id));
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

function runtimeDetails(inventory, serverId, only = null) {
  const section = el("section", "runtime-detail");
  section.append(el("h4", null, "Binaries and versions"));
  if (!inventory?.observed_at) {
    section.append(el("p", "muted", "Not assessed — no binary observation is available."));
    if (inventory?.failure_reason) section.append(el("p", "muted", inventory.failure_reason));
    return section;
  }
  const current = inventory.freshness === "fresh";
  if (!current) section.append(el("p", "runtime-freshness stale",
    `Binary evidence is stale${inventory.last_attempt === "collection_failed" ? " · latest collection failed" : ""}.`));
  const components = groupedRuntimes((inventory.components || []).filter((c) =>
    !only || (c.name === only && (!ui.binaryVersion || runtimeVersion(c) === ui.binaryVersion)))).sort((a, b) =>
    a.name.localeCompare(b.name) || runtimeVersion(a).localeCompare(runtimeVersion(b), undefined, { numeric: true }) ||
    (a.executable || "").localeCompare(b.executable || ""));
  const list = el("div", "runtime-list");
  for (const c of components) {
    const details = el("details", "binary-accordion");
    const key = JSON.stringify([serverId, c.name, c.version, c.executable, c.scope, c.container_id]);
    details.open = Object.hasOwn(ui.binaryOpen, key) ? ui.binaryOpen[key] : Boolean(only) ||
      Boolean(ui.picked === serverId && ui.runtime === c.name && (!ui.binaryVersion || runtimeVersion(c) === ui.binaryVersion));
    details.addEventListener("toggle", () => { ui.binaryOpen[key] = details.open; });
    const summary = el("summary", "binary-summary");
    summary.append(el("b", "binary-name", c.name), el("code", "binary-version", c.version ? runtimeVersion(c) : "Version unknown"));
    const state = c.running ? "running" : "inactive";
    summary.append(el("span", `runtime-state ${state}`, `${current ? "" : "Last observed: "}${c.running ? "Running" : "Inactive"}`));
    const content = el("div", "binary-content");
    if (!c.running) content.append(el("p", "runtime-context", "Installed, but not observed running at this check. Scheduled or short-lived jobs may run between checks."));
    if (c.version && runtimeVersion(c) !== c.version) content.append(el("p", "runtime-evidence", `File metadata: ${c.version}`));
    content.append(el("p", "runtime-context", [c.service, c.container_name ? `Container: ${c.container_name}` : c.scope].filter(Boolean).join(" · ")));
    if (c.executable) content.append(el("code", "runtime-path", c.executable));
    const evidence = {
      running_binary_file_metadata: "Version from executable file metadata",
      executable_self_report: "Version reported by active executable image",
      installed_executable_self_report: "Version reported by installed executable",
      installed_binary_file_metadata: "Version from installed file metadata",
      installed_executable_unverified: "Installed executable · version could not be verified",
    }[c.evidence_kind] || "Version could not be verified";
    content.append(el("p", "runtime-evidence", `${evidence}${c.process_count ? ` · ${c.process_count} process${c.process_count === 1 ? "" : "es"}` : ""}`));
    if (c.package_version) content.append(el("p", "runtime-evidence", `Package: ${c.package_name} ${c.package_version}${c.package_arch ? ` · ${c.package_arch}` : ""}`));
    const link = el("a", "binary-link", "Link to this binary");
    link.href = binaryUrl(c.name, runtimeVersion(c), serverId).href;
    content.append(link);
    details.append(summary, content);
    list.append(details);
  }
  section.append(list);
  if (!components.length) section.append(el("p", "muted", "No binaries recorded. Installed coverage may be incomplete."));
  if (inventory.collection_state === "partial" || inventory.components_omitted) section.append(el("p", "stale", "Partial collection — additional components may be missing."));
  for (const gap of inventory.gaps || []) section.append(el("p", "runtime-evidence", gap));
  return section;
}

function renderCompare(s, groupKey) {
  const panel = el("section", "server-details compare-details");
  const section = runtimeDetails(s.runtimeInventory, s.id, ui.runtime);
  section.querySelector("h4").textContent = ui.binaryVersion ? `${ui.runtime} ${ui.binaryVersion}` : ui.runtime;
  const full = el("button", "binary-link compare-full", "All server details");
  full.type = "button";
  full.addEventListener("click", () => pick(s.id, groupKey));
  section.append(full);
  panel.append(section);
  return panel;
}

function toggleCompare(id, trigger) {
  if (ui.compareClosed.has(id)) ui.compareClosed.delete(id); else ui.compareClosed.add(id);
  if (ui.view === "location") renderPicture(); else renderGroups();
  document.querySelectorAll(".row").forEach((button) => {
    if (button.dataset.id === id && button.getAttribute("aria-controls") === trigger.getAttribute("aria-controls")) button.focus({ preventScroll: true });
  });
}

// One line per reported version of the selected binary: how many servers run it and how many only
// have it installed. Selecting a version narrows the servers; selecting it again clears it.
function renderVersionSummary(section, fresh) {
  const versions = new Map();
  for (const server of fresh) {
    for (const c of server.runtimeInventory.components || []) {
      if (c.name !== ui.runtime) continue;
      const v = c.version ? runtimeVersion(c) : "Version unknown";
      if (!versions.has(v)) versions.set(v, { running: new Set(), inactive: new Set() });
      versions.get(v)[c.running ? "running" : "inactive"].add(server.id);
    }
  }
  if (!versions.size) return;
  const wrap = el("div", "version-summary");
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", `${ui.runtime} versions`);
  const sorted = [...versions].sort(([a], [b]) => b.localeCompare(a, undefined, { numeric: true }));
  for (const [version, seen] of sorted) {
    const servers = new Set([...seen.running, ...seen.inactive]).size;
    const b = el("button", "version-chip");
    b.type = "button";
    b.setAttribute("aria-pressed", String(ui.binaryVersion === version));
    b.append(el("code", null, version), el("span", null,
      `${servers} server${servers === 1 ? "" : "s"}${seen.running.size ? ` · ${seen.running.size} running` : ""}${seen.inactive.size ? ` · ${seen.inactive.size} inactive` : ""}`));
    b.addEventListener("click", () => {
      ui.binaryVersion = ui.binaryVersion === version ? null : version;
      writeBinaryUrl();
      render();
    });
    wrap.append(b);
  }
  const all = el("button", "binary-version-filter", ui.compareClosed.size ? "Expand all" : "Collapse all");
  all.type = "button";
  all.addEventListener("click", () => {
    if (ui.compareClosed.size) ui.compareClosed.clear();
    else fresh.forEach((server) => ui.compareClosed.add(server.id));
    render();
  });
  wrap.append(all);
  section.append(wrap);
}

function renderRuntimes() {
  const section = document.getElementById("runtime-overview");
  const fresh = data.servers.filter((s) => s.runtimeInventory?.freshness === "fresh");
  section.replaceChildren(el("p", "runtime-coverage", `${fresh.length} of ${data.servers.length} servers have recent binary observations. Filter a binary to review running and inactive versions.`));
  const counts = new Map();
  for (const server of fresh) {
    const names = new Set((server.runtimeInventory.components || []).map((c) => c.name));
    for (const name of names) counts.set(name, (counts.get(name) || 0) + 1);
  }
  if (ui.runtime) ui.runtime = [...counts.keys()].find((name) => name.toLowerCase() === ui.runtime.toLowerCase()) || ui.runtime;
  if (ui.runtime && !counts.has(ui.runtime)) counts.set(ui.runtime, 0);
  if (ui.binaryVersion) {
    const clear = el("button", "binary-version-filter", `Version ${ui.binaryVersion} ×`);
    clear.type = "button";
    clear.setAttribute("aria-label", `Clear version filter ${ui.binaryVersion}`);
    clear.addEventListener("click", () => { ui.binaryVersion = null; writeBinaryUrl(); render(); });
    section.append(clear);
  }
  if (ui.runtime) renderVersionSummary(section, fresh);
  const choices = [["", "All binaries"], ...[...counts].sort(([a], [b]) => a.localeCompare(b))
    .map(([name, count]) => [name, `${name} · ${count}`])];
  const select = document.getElementById("binary");
  const signature = JSON.stringify(choices);
  if (select.dataset.choices !== signature) {
    select.replaceChildren(...choices.map(([value, label]) => {
      const option = el("option", null, label);
      option.value = value;
      return option;
    }));
    select.dataset.choices = signature;
  }
  select.value = ui.runtime || "";
}

function pick(id, groupKey = ui.pickedGroup, trigger = null) {
  const close = ui.picked === id && ui.pickedGroup === groupKey;
  if (trigger) focusReturn = { id: trigger.dataset.id, controls: trigger.getAttribute("aria-controls") };
  ui.picked = close ? null : id;
  ui.pickedGroup = ui.picked ? groupKey : null;
  writeBinaryUrl();
  if (ui.view === "location") renderPicture(); else renderGroups();
  syncServerFocus();
  if (!ui.picked && focusReturn) {
    [...document.querySelectorAll(".row")].find((button) =>
      button.dataset.id === focusReturn.id && button.getAttribute("aria-controls") === focusReturn.controls)?.focus({ preventScroll: true });
  }
  if (trigger) document.querySelectorAll(".row").forEach((button) => {
    if (button.dataset.id === trigger.dataset.id && button.getAttribute("aria-controls") === trigger.getAttribute("aria-controls")) button.focus({ preventScroll: true });
  });
}

const focusVeil = el("div", "server-focus-veil");
focusVeil.hidden = true;
focusVeil.setAttribute("aria-hidden", "true");
focusVeil.addEventListener("click", () => pick(null));
document.body.append(focusVeil);
let focusInert = [];
let focusReturn = null;

function syncServerFocus() {
  for (const element of focusInert) element.inert = false;
  focusInert = [];
  const selected = document.querySelector(".server-focus");
  focusVeil.hidden = !selected;
  if (!selected) return;
  // Leave the selected inline server interactive; outside clicks land on the glass.
  for (let child = selected; child && child !== document.body; child = child.parentElement) {
    for (const sibling of child.parentElement.children) {
      if (sibling === child || sibling === focusVeil || sibling.tagName === "SCRIPT" || sibling.inert) continue;
      sibling.inert = true;
      focusInert.push(sibling);
    }
  }
}

for (const container of [document.getElementById("groups"), document.getElementById("picture")]) {
  new MutationObserver(syncServerFocus).observe(container, { childList: true });
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
  renderRuntimes();
  renderPicture();
  renderGroups();
}

for (const g of ["view", "filter"]) {
  document.getElementById(g).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    ui[g] = g === "filter" && ui.filter === b.dataset.v ? "all" : b.dataset.v;
    if (g === "view") { ui.place = null; remember(); }
    render();
  });
}
document.getElementById("binary").addEventListener("change", (e) => {
  ui.runtime = e.target.value || null;
  ui.binaryVersion = null;
  ui.picked = null;
  ui.compareClosed.clear();
  writeBinaryUrl();
  renderRuntimes();
  renderPicture();
  renderGroups();
});
document.getElementById("search").addEventListener("input", (e) => { ui.query = e.target.value.trim().toLowerCase(); if (ui.view === "location") renderPicture(); else renderGroups(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && ui.picked) pick(null);
  if (e.key === "/" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)) { e.preventDefault(); document.getElementById("search").focus(); }
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
