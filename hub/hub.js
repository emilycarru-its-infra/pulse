// The hub: one overall state, active incidents and maintenance, a card per product with its live
// one-line summary, every system with 90 days of history, and the past week's incidents.
//
// The site supplies /hub/status.json (systems, incidents, history) and /hub/products.json (the
// products and where their summaries are). Times in status.json are ISO 8601 or relative to now
// ("-2h", "+3d", "-40m"), so a sample file always looks current. "sample": true shows a banner
// that says so.

const DAY = 86400000;
const DAYS = 90;
const LEVEL = { ok: "Normal", warn: "Degraded", bad: "Down", idle: "No data" };
const STATE = {
  ok: { word: "Operational", chip: "ok" },
  warn: { word: "Degraded", chip: "warn" },
  bad: { word: "Outage", chip: "bad" },
  maint: { word: "Maintenance", chip: "maint" },
};
const RANK = { ok: 0, maint: 1, warn: 2, bad: 3 };
const IMPACT = { minor: "warn", major: "bad", maintenance: "maint" };
const ORDER = ["available", "possibly_free", "in_use", "offline", "out_of_service"];
const COLOUR = { available: "var(--ok)", possibly_free: "var(--warn)", in_use: "var(--text-primary)",
  offline: "var(--idle)", out_of_service: "var(--bad)" };

function when(value, now) {
  if (value == null) return null;
  const m = /^([+-]\d+(?:\.\d+)?)([mhd])$/.exec(String(value).trim());
  if (m) return new Date(now + Number(m[1]) * { m: 60000, h: 3600000, d: DAY }[m[2]]);
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

const worst = (levels) => levels.reduce((a, b) => (RANK[b] > RANK[a] ? b : a), "ok");
const dayKey = (d) => d.toLocaleDateString("en-CA");
const fmtDay = (d) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
const fmtTime = (d) => d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function chip(level, word) {
  return el("span", `chip ${STATE[level].chip}`, word ?? STATE[level].word);
}

// Incidents with their times resolved, and the level each puts on the systems it names.
function incidents(data, now) {
  return (data.incidents || []).map((i) => {
    const start = when(i.start, now);
    const end = when(i.end, now);
    const level = IMPACT[i.impact] || "warn";
    return {
      ...i, start, end, level,
      active: start && start.getTime() <= now && (!end || end.getTime() > now),
      upcoming: start && start.getTime() > now,
      updates: (i.updates || []).map((u) => ({ ...u, at: when(u.at, now) }))
        .sort((a, b) => b.at - a.at),
    };
  });
}

// Per system: the worst level on each of the last 90 days and the minutes down, from the
// incidents that name it and any extra history the site lists.
function history(component, list, now) {
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  const days = Array.from({ length: DAYS }, (_, i) => ({
    date: new Date(today.getTime() - (DAYS - 1 - i) * DAY), level: "ok", notes: [] }));
  let weighted = 0;
  const mark = (date, level, minutes, note) => {
    const idx = DAYS - 1 - Math.round((today - new Date(date).setHours(0, 0, 0, 0)) / DAY);
    if (idx < 0 || idx >= DAYS) return;
    const day = days[idx];
    day.level = worst([day.level, level]);
    if (note) day.notes.push(note);
    weighted += level === "bad" ? minutes : level === "warn" ? minutes * 0.3 : 0;
  };
  for (const h of component.history || []) {
    mark(now - h.daysAgo * DAY, h.level || "warn", h.minutes || 0, h.note);
  }
  for (const i of list) {
    if (!i.start || i.upcoming || !(i.components || []).includes(component.id)) continue;
    const stop = i.end ? i.end.getTime() : now;
    mark(i.start, i.level, Math.max(0, (stop - i.start.getTime()) / 60000), i.title);
  }
  const uptime = Math.max(0, 100 * (1 - weighted / (DAYS * 1440)));
  return { days, uptime };
}

function bars(days) {
  const wrap = el("div", "bars");
  const bad = days.filter((d) => d.level !== "ok").length;
  wrap.setAttribute("role", "img");
  wrap.setAttribute("aria-label", bad ? `${bad} of the last ${DAYS} days had issues` : `No issues in the last ${DAYS} days`);
  for (const d of days) {
    const s = el("i", `day ${d.level}`);
    s.title = `${fmtDay(d.date)}: ${d.notes.length ? d.notes.join("; ") : "No issues"}`;
    wrap.append(s);
  }
  return wrap;
}

function incidentCard(i, components) {
  const li = el("li", `card incident ${i.level}`);
  const head = el("div", "incident-head");
  const h = el("h3", null, i.title);
  head.append(h, chip(i.level, i.upcoming ? "Scheduled" : i.level === "maint" ? "In progress" : STATE[i.level].word));
  li.append(head);
  const affected = (i.components || []).map((id) => components.get(id)?.name).filter(Boolean);
  const meta = i.upcoming
    ? `${fmtTime(i.start)} to ${i.end ? fmtTime(i.end) : "until done"}`
    : `Since ${fmtTime(i.start)}`;
  li.append(el("p", "fine", affected.length ? `${meta} · Affects ${affected.join(", ")}` : meta));
  if (i.updates.length) {
    const ol = el("ol", "updates");
    for (const u of i.updates) {
      const row = el("li");
      row.append(el("strong", null, u.status ? `${u.status[0].toUpperCase()}${u.status.slice(1)}` : "Update"),
        el("span", null, ` ${u.body}`), el("time", "fine", fmtTime(u.at)));
      ol.append(row);
    }
    li.append(ol);
  }
  return li;
}

function productCard(p, s) {
  const node = el(p.soon ? "div" : "a", `card product${p.soon ? " soon" : ""}`);
  if (!p.soon) node.href = p.href;
  const head = el("div", "head");
  head.append(el("h3", null, p.title),
    p.soon ? el("span", "chip idle", "Coming")
      : s ? el("span", `chip ${s.level}`, LEVEL[s.level]) : el("span", "chip bad", "Not answering"));
  node.append(head, el("p", "line", p.soon ? "Not yet live" : s ? s.line : "The product did not answer"));
  if (s?.counts && s.seats) {
    const meter = el("div", "meter");
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", ORDER.map((k) => `${s.counts[k] || 0} ${k.replace(/_/g, " ")}`).join(", "));
    for (const k of ORDER) {
      if (!s.counts[k]) continue;
      const seg = el("span");
      seg.style.width = `${(100 * s.counts[k]) / s.seats}%`;
      seg.style.background = COLOUR[k];
      meter.append(seg);
    }
    node.append(meter);
  }
  node.append(el("p", "about", p.about + (p.restricted ? ` (${p.restricted === true ? "restricted audience" : p.restricted})` : "")));
  const li = el("li");
  li.append(node);
  return li;
}

function render(data, products, summaries) {
  const now = Date.now();
  const list = incidents(data, now);
  const components = new Map();
  for (const g of data.groups || []) for (const c of g.components || []) components.set(c.id, c);
  const current = new Map([...components.keys()].map((id) => [id, "ok"]));
  for (const i of list.filter((x) => x.active)) {
    for (const id of i.components || []) if (current.has(id)) current.set(id, worst([current.get(id), i.level]));
  }

  const sample = document.getElementById("sample");
  sample.hidden = !data.sample;
  sample.textContent = data.sampleNote || "Mockup with sample data: the systems are real, their states and incidents are not.";

  const overall = worst([...current.values()]);
  const down = [...current].filter(([, l]) => l !== "ok").map(([id]) => components.get(id).name);
  const box = document.getElementById("overall");
  box.className = `overall card ${overall}`;
  document.getElementById("overall-title").textContent =
    overall === "ok" ? "All systems operational"
      : overall === "bad" ? `Outage: ${down.join(", ")}`
        : overall === "warn" ? `Degraded: ${down.join(", ")}`
          : `Maintenance in progress: ${down.join(", ")}`;
  document.getElementById("updated").textContent = `Updated ${new Date(now).toLocaleTimeString()}`;

  const active = list.filter((i) => i.active && i.level !== "maint").sort((a, b) => RANK[b.level] - RANK[a.level]);
  document.getElementById("active").replaceChildren(...active.map((i) => incidentCard(i, components)));
  document.getElementById("active-wrap").hidden = !active.length;
  const maint = list.filter((i) => i.level === "maint" && (i.active || i.upcoming)).sort((a, b) => a.start - b.start);
  document.getElementById("maintenance").replaceChildren(...maint.map((i) => incidentCard(i, components)));
  document.getElementById("maintenance-wrap").hidden = !maint.length;

  document.getElementById("products").replaceChildren(...products.map((p, i) => productCard(p, summaries[i])));

  const expanded = new Map([...document.querySelectorAll(".group")].map((g) => [g.dataset.group, g.open]));
  const groups = (data.groups || []).map((g) => {
    const levels = (g.components || []).map((c) => current.get(c.id));
    const level = worst(levels);
    const det = el("details", "group card");
    det.dataset.group = g.name;
    det.open = expanded.get(g.name) ?? true;
    const sum = el("summary");
    sum.append(el("h3", null, g.name), chip(level, level === "ok" ? "Operational" : `${levels.filter((l) => l !== "ok").length} affected`));
    det.append(sum);
    for (const c of g.components || []) {
      const { days, uptime } = history(c, list, now);
      const row = el("div", "system");
      const name = el("div", "system-name");
      const title = c.href ? el("a", null, c.name) : el("span", null, c.name);
      if (c.href) title.href = c.href;
      name.append(title);
      if (c.about) name.append(el("span", "fine", c.about));
      const lvl = current.get(c.id);
      row.append(name, chip(lvl), bars(days), el("span", "uptime fine", `${uptime.toFixed(2)}% uptime`));
      det.append(row);
    }
    return det;
  });
  document.getElementById("groups").replaceChildren(...groups);

  const past = list.filter((i) => i.end && i.end.getTime() <= now);
  const days = Array.from({ length: 7 }, (_, n) => new Date(now - n * DAY));
  document.getElementById("history").replaceChildren(...days.map((d) => {
    const li = el("li", "history-day");
    li.append(el("h3", null, fmtDay(d)));
    const those = past.filter((i) => dayKey(i.start) === dayKey(d));
    if (!those.length) li.append(el("p", "fine", "No incidents reported."));
    for (const i of those) {
      const item = el("div", "past");
      const head = el("div", "past-head");
      head.append(el("strong", null, i.title), chip(i.level, i.level === "maint" ? "Maintenance" : "Resolved"));
      item.append(head);
      const last = i.updates[0];
      if (last) item.append(el("p", null, last.body));
      item.append(el("p", "fine", `${fmtTime(i.start)} to ${fmtTime(i.end)}`));
      li.append(item);
    }
    return li;
  }));
}

(async () => {
  const brand = await Pulse.shell({ current: "hub", context: "Shared university systems, right now and over the last 90 days" });
  if (brand.foot) document.getElementById("foot").textContent = brand.foot;
  const products = await fetch("/hub/products.json").then((r) => r.json()).catch(() => []);
  Pulse.poll(async () => {
    const data = await fetch("/hub/status.json", { cache: "no-store" }).then((r) => r.json()).catch(() => ({}));
    // A product's summary is its live /api/summary, or a fixed one the site supplies for a mockup.
    const summaries = await Promise.all(products.map((p) =>
      p.soon ? null : typeof p.summary === "object" ? p.summary
        : fetch(p.summary).then((r) => (r.ok ? r.json() : null)).catch(() => null)));
    render(data, products, summaries);
  }, 30000);
})();

Pulse.masonry(document.getElementById("groups"));
