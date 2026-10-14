const NS = "http://www.w3.org/2000/svg";
const WORD = { ready: "Ready", printing: "Printing", attention: "Needs attention", error: "Stopped",
  offline: "Not responding" };
const ORDER = ["ready", "printing", "attention", "error", "offline"];
const WORKING = new Set(["ready", "printing"]);
const SIZE = 44; // a printer's square on the plan, in plan pixels

const state = { floor: null, audience: "all", mode: "map", picked: null, printer: null, hover: null, status: null, drawn: null };
const phone = window.matchMedia("(max-width: 700px)");
const svg = document.getElementById("map");
const content = document.getElementById("content");
const vp = Pulse.viewport(svg, content, {
  onChange: (k) => {
    document.getElementById("zoom-level").textContent = `${Math.round(k * 100)}%`;
    svg.classList.toggle("far", k < 0.45);
    placeBadges(k);
  },
});

const dark = window.matchMedia("(prefers-color-scheme: dark)");
const tintPlan = () => {
  const plan = content.querySelector(".plan");
  if (dark.matches) plan?.setAttribute("filter", "url(#plan-light)");
  else plan?.removeAttribute("filter");
};
dark.addEventListener("change", tintPlan);
phone.addEventListener("change", () => { state.drawn = null; render(); });

const el = (name, attrs = {}, parent) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  parent?.append(node);
  return node;
};
const shown = (p) => state.audience === "all" || p.audience === state.audience;
// The short label on a printer's square: what it prints.
const kindOf = (p) => (p.inkjet ? "INK" : p.colour ? "CLR" : "BW");
const kindWord = (p) => (p.inkjet ? "Large-format inkjet" : p.colour ? "Colour laser" : "Black-and-white laser");
// A room's name from the inventory location ("R101 - Print Room" is "Print Room").
const placeName = (p) => p.location.replace(/^\S+\s*-\s*/, "").trim() || p.location;

// Rooms: every printer in one room shares a badge, a drawer and a list card.
function rooms() {
  const map = new Map();
  for (const p of state.status.printers) {
    if (!shown(p)) continue;
    const id = `${p.floor ?? "x"}-${p.room}`;
    if (!map.has(id)) map.set(id, { id, room: p.room, floor: p.floor ?? null, name: placeName(p), printers: [] });
    map.get(id).printers.push(p);
  }
  return [...map.values()];
}
const working = (ps) => ps.filter((p) => WORKING.has(p.state)).length;
const countsOf = (ps) => Object.fromEntries(ORDER.map((k) => [k, ps.filter((p) => p.state === k).length]));
const countsLine = (c) => ["printing", "attention", "error", "offline"]
  .filter((k) => c[k]).map((k) => `<b>${c[k]}</b> ${WORD[k].toLowerCase()}`).join(" · ") || "Every printer is ready";

function printerURL(extra = {}) {
  return Pulse.linkURL({ view: state.mode, floor: state.floor, room: state.picked, printer: state.printer, audience: state.audience === "all" ? "" : state.audience, ...extra }, true);
}
function recordView(push = true) {
  const url = printerURL();
  if (url !== location.href) history[push ? "pushState" : "replaceState"](null, "", url);
}
function readView() {
  const params = new URLSearchParams(location.hash.slice(1));
  state.mode = params.get("view") === "list" ? "list" : params.get("view") === "map" || params.has("room") ? "map" : phone.matches ? "list" : "map";
  state.floor = params.get("floor"); state.picked = params.get("room"); state.printer = params.get("printer");
  state.audience = ["students", "staff"].includes(params.get("audience")) ? params.get("audience") : "all";
  state.drawn = null;
  for (const [id, value] of [["mode", state.mode], ["audience", state.audience]]) for (const b of document.querySelectorAll(`#${id} button`)) b.setAttribute("aria-pressed", String(b.dataset.v === value));
}
window.addEventListener("popstate", () => { readView(); if (state.status) { render(); if (state.picked && state.mode === "map") pick(state.picked, state.printer, true, false); } });
window.addEventListener("hashchange", () => { if (location.href !== printerURL()) { readView(); if (state.status) render(); } });

function renderFloors() {
  const tabs = document.getElementById("floors");
  const all = rooms();
  tabs.replaceChildren(...state.status.floors.map((f) => {
    const ps = all.filter((r) => r.floor === f.id).flatMap((r) => r.printers);
    const b = document.createElement("button");
    b.type = "button";
    b.role = "tab";
    b.dataset.id = f.id;
    b.setAttribute("aria-selected", String(f.id === state.floor));
    const name = f.name.replace(/ Floor$/, '<span class="word"> Floor</span>');
    b.innerHTML = `${name}<small>${working(ps)}<span class="tight"> ready</span><span class="word"> of ${ps.length}</span></small>`;
    return b;
  }));
}

// A room's printers sit side by side, centred on the room's label point.
function layout(room) {
  const ps = room.printers.filter((p) => "x" in p);
  const gap = SIZE * 1.25;
  const cols = Math.min(ps.length, 3);
  return ps.map((p, i) => ({
    p,
    x: p.x + ((i % cols) - (cols - 1) / 2) * gap,
    y: p.y + Math.floor(i / cols) * gap,
  }));
}

function drawFloor() {
  const floor = state.status.floors.find((f) => f.id === state.floor);
  if (!floor) return;
  if (state.drawn !== floor.id) {
    content.replaceChildren();
    el("image", { href: `catalog/${floor.plan}`, width: floor.width, height: floor.height, class: "plan" }, content);
    el("g", { id: "rooms-layer" }, content);
    tintPlan();
    state.drawn = floor.id;
    const home = homeFor(floor);
    svg.style.height = phone.matches
      ? `${Math.round(Math.min(Math.max(svg.clientWidth * home.h / home.w + 48, 220), innerHeight * 0.62))}px` : "";
    vp.setHome(home);
  }
  const layer = document.getElementById("rooms-layer");
  layer.replaceChildren();
  const labels = el("g", { class: "labels" });
  const font = phone.matches ? 11 : 13;
  for (const room of rooms().filter((r) => r.floor === floor.id)) {
    const spots = layout(room);
    if (!spots.length) continue;
    const ok = working(room.printers);
    const g = el("g", { class: `space${ok ? "" : " none"}${state.picked === room.id ? " picked" : ""}`, "data-id": room.id }, layer);
    const pad = SIZE * 0.35;
    const rx = spots.map((s) => s.x), ry = spots.map((s) => s.y);
    el("rect", { x: Math.min(...rx) - SIZE / 2 - pad, y: Math.min(...ry) - SIZE / 2 - pad,
      width: Math.max(...rx) - Math.min(...rx) + SIZE + pad * 2, height: Math.max(...ry) - Math.min(...ry) + SIZE + pad * 2,
      rx: 4, class: "room" }, g);
    for (const { p, x, y } of spots) {
      const one = el("g", { class: `printer-g${state.printer === p.id ? " picked" : ""}`, transform: `translate(${x},${y})`,
        tabindex: 0, role: "button", "data-id": room.id, "data-printer": p.id,
        "aria-label": `${p.name}, room ${p.room}: ${WORD[p.state]}` }, g);
      const sq = el("rect", { x: -SIZE / 2, y: -SIZE / 2, width: SIZE, height: SIZE, rx: 5, class: `printer ${p.state}` }, one);
      el("title", {}, sq).textContent = `${p.name}: ${WORD[p.state]}${p.detail && p.detail !== WORD[p.state] ? ` (${p.detail})` : ""}`;
      el("text", { y: 0.5, class: `num ${p.state}`, "font-size": SIZE * 0.3 }, one).textContent = kindOf(p);
    }
    const xs = spots.map((s) => s.x), ys = spots.map((s) => s.y);
    const bx = Math.min(...xs) - SIZE / 2 - pad, by = Math.min(...ys) - SIZE / 2 - pad - 4;
    const badge = el("g", { class: `badge${ok ? "" : " none"}`, "data-x": bx, "data-y": by, "data-seats": room.printers.length,
      "data-id": room.id }, labels);
    const faces = [["short", [[room.room]]], ["long", [[`${room.name === room.room ? room.room : room.name} `], [`${ok}/${room.printers.length} ready`, "free"]]]];
    for (const [face, parts] of faces) {
      const text = el("text", { x: 7, y: -7, "font-size": font }, el("g", { class: face }, badge));
      for (const [words, cls] of parts) el("tspan", cls ? { class: cls } : {}, text).textContent = words;
    }
  }
  layer.append(labels);
  for (const badge of labels.children) {
    for (const face of badge.children) {
      const bb = face.firstChild.getBBox();
      face.prepend(el("rect", { x: 0, y: bb.y - 4, width: bb.width + 14, height: bb.height + 8, rx: 3 }));
      if (face.classList.contains("short")) Object.assign(badge.dataset, { w: bb.width + 14, h: bb.height + 8 });
    }
  }
  placeBadges();
  openBadges();
}

// Room labels keep one size on screen whatever the zoom; one that would cover another is hidden.
function placeBadges(k = vp.k) {
  const placed = [];
  const badges = [...content.querySelectorAll(".badge")].sort((a, b) => b.dataset.seats - a.dataset.seats);
  for (const b of badges) {
    b.setAttribute("transform", `translate(${b.dataset.x},${b.dataset.y}) scale(${1 / k})`);
    const w = +b.dataset.w, h = +b.dataset.h;
    const box = { x: b.dataset.x * k, y: b.dataset.y * k - h, w, h };
    const clash = placed.some((o) => box.x < o.x + o.w && o.x < box.x + box.w && box.y < o.y + o.h && o.y < box.y + box.h);
    b.style.display = clash ? "none" : "";
    if (!clash) placed.push(box);
  }
}

function openBadges() {
  for (const b of content.querySelectorAll(".badge")) {
    const open = b.dataset.id === state.hover || b.dataset.id === state.picked;
    b.classList.toggle("open", open);
    if (open) b.parentNode.append(b);
  }
}

function homeFor(floor) {
  const spots = rooms().filter((r) => r.floor === floor.id).flatMap(layout);
  if (!phone.matches || !spots.length) return { x: 0, y: 0, w: floor.width, h: floor.height };
  const x0 = Math.min(...spots.map((s) => s.x)), y0 = Math.min(...spots.map((s) => s.y));
  const x1 = Math.max(...spots.map((s) => s.x)), y1 = Math.max(...spots.map((s) => s.y));
  const m = Math.max(x1 - x0, y1 - y0) * 0.08 + SIZE * 2;
  return { x: x0 - m, y: y0 - m, w: x1 - x0 + m * 2, h: y1 - y0 + m * 2 };
}

// One printer: its state and what is wrong, then supplies, paper and the queues it serves.
function printerRow(p) {
  const row = document.createElement("div");
  row.className = `printer-row${state.printer === p.id ? " picked" : ""}`;
  row.dataset.printer = p.id;
  row.innerHTML = `<span class="ptag ${p.state}"></span><div class="body">
      <p class="pname"></p><p class="meta"></p><p class="what ${p.state}"></p>
      <div class="levels"></div><p class="meta stats"></p><p class="queues"></p></div>`;
  row.querySelector(".ptag").textContent = kindOf(p);
  row.querySelector(".ptag").setAttribute("aria-hidden", "true");
  const title = row.querySelector(".pname"); title.textContent = p.name;
  title.classList.add("share-heading", "share-scope");
  const room = rooms().find((r) => r.printers.some((item) => item.id === p.id));
  title.append(Pulse.copyLink(() => printerURL({ view: room?.floor ? "map" : "list", floor: room?.floor, room: room?.id, printer: p.id }), p.name));
  row.querySelector(".meta").textContent = `${p.model} · ${kindWord(p)} · ${p.audience === "students" ? "Students" : "Staff"}`;
  const what = row.querySelector(".what");
  what.textContent = p.detail && p.detail !== WORD[p.state] ? `${WORD[p.state]}: ${p.detail}` : WORD[p.state];
  if (p.state === "offline") what.textContent += `, last heard ${Pulse.ago(p.lastSeen)}`;
  row.querySelector(".levels").replaceChildren(...[...p.supplies, ...p.trays.map((t) => ({ ...t, paper: true }))].map(level));
  row.querySelector(".stats").innerHTML = `<b>${p.queue}</b> waiting · <b>${p.jobsToday}</b> jobs today`;
  row.querySelector(".queues").textContent = p.queues.join(" · ");
  return row;
}

function level(s) {
  const div = document.createElement("div");
  div.className = "level";
  const cls = s.level <= 0 ? "out" : s.level <= 12 ? "low" : s.paper ? "" : `k-${s.name.toLowerCase().replace(/^(photo|matte) /, "")}`;
  div.innerHTML = `<span><span class="lname"></span> <b>${s.level}%</b></span><span class="bar"><span class="${cls}" style="width:${Math.max(0, s.level)}%"></span></span>`;
  div.querySelector(".lname").textContent = s.name;
  div.title = `${s.name}: ${s.level}%`;
  return div;
}

// The list has one card per room, rooms with a printer in trouble first, then by floor and room.
function renderList() {
  const cards = rooms()
    .filter((r) => !state.floor || r.floor === state.floor)
    .map((r) => ({ r, c: countsOf(r.printers) }))
    .sort((a, b) => (b.c.error + b.c.offline) - (a.c.error + a.c.offline)
      || (a.r.floor ?? "~").localeCompare(b.r.floor ?? "~") || a.r.room.localeCompare(b.r.room))
    .map(({ r, c }) => {
      const card = document.createElement("article");
      card.className = "card space-card";
      card.innerHTML = `<div class="head"><div><p class="room"></p><h3></h3><div class="metadata"><p class="kicker"></p></div></div>
        <p class="free"><b>${working(r.printers)}</b><span>ready of ${r.printers.length}</span></p></div>
        <p class="counts">${countsLine(c)}</p><div class="printers"></div>`;
      const title = card.querySelector(".room"); title.textContent = r.room;
      const heading = document.createElement("div"); heading.className = "share-heading share-scope";
      title.replaceWith(heading); heading.append(title, Pulse.copyLink(() => printerURL({ view: r.floor ? "map" : "list", floor: r.floor, room: r.id, printer: "" }), r.room));
      card.querySelector("h3").textContent = r.name === r.room ? "" : r.name;
      const floorName = r.floor ? state.status.floors.find((f) => f.id === r.floor)?.name : "Not on the floorplans";
      card.querySelector(".kicker").textContent = floorName ?? "";
      if (r.floor && r.printers.some((p) => "x" in p)) {
        const go = document.createElement("button");
        go.type = "button";
        go.className = "on-map";
        go.setAttribute("aria-label", `Show ${r.name} on map`);
        go.title = `Show ${r.name} on map`;
        go.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3Z M9 3v15 M15 6v15"/></svg>';
        go.onclick = () => showOnMap(r);
        card.querySelector(".metadata").append(go);
      }
      card.querySelector(".printers").replaceChildren(...r.printers.map(printerRow));
      return card;
    });
  document.getElementById("spaces").replaceChildren(...cards);
}

function renderDrawer() {
  const drawer = document.getElementById("drawer");
  const room = rooms().find((r) => r.id === state.picked);
  if (!room || state.mode !== "map") {
    drawer.hidden = true;
    return;
  }
  const c = countsOf(room.printers);
  const floor = state.status.floors.find((f) => f.id === room.floor);
  drawer.hidden = false;
  drawer.innerHTML = `<div class="head"><div><p class="kicker"></p><h3></h3></div>
      <button type="button" class="close" aria-label="Close details">Close</button></div>
    <p class="big">${working(room.printers)}</p><p class="of">ready of ${room.printers.length}</p>
    <p class="counts">${countsLine(c)}</p><h4>Printers</h4><div class="printers"></div>`;
  drawer.querySelector(".kicker").textContent = [floor?.name, room.room].filter(Boolean).join(" · ");
  const title = drawer.querySelector("h3"); title.textContent = room.name;
  const heading = document.createElement("div"); heading.className = "share-heading share-scope";
  title.replaceWith(heading); heading.append(title, Pulse.copyLink(() => printerURL({ printer: "" }), room.name));
  drawer.querySelector(".printers").replaceChildren(...room.printers.map(printerRow));
  drawer.querySelector(".close").onclick = () => pick(null);
  drawer.querySelector(".printer-row.picked")?.scrollIntoView({ block: "nearest" });
}

function render() {
  if (!state.status) return;
  document.getElementById("mock").hidden = !state.status.sample;
  const known = state.status.floors.some((f) => f.id === state.floor);
  if (state.mode === "map" && !known) state.floor = state.status.floors[0]?.id ?? null;
  else if (state.floor && !known) state.floor = null;
  renderFloors();
  const all = rooms().flatMap((r) => r.printers);
  document.getElementById("total").innerHTML =
    `<b>${working(all)}</b> ready<span class="word"> of ${all.length} on campus</span>`;
  document.getElementById("map-view").hidden = state.mode !== "map";
  document.getElementById("list-view").hidden = state.mode !== "list";
  document.getElementById("hint").hidden = state.mode !== "map";
  if (state.mode === "map") drawFloor();
  else renderList();
  renderDrawer();
}

function showOnMap(room) {
  state.mode = "map";
  for (const b of document.querySelectorAll("#mode button")) b.setAttribute("aria-pressed", String(b.dataset.v === "map"));
  if (room.floor !== state.floor) setFloor(room.floor);
  state.drawn = null;
  render();
  document.getElementById("map-view").scrollIntoView({ block: "start" });
  requestAnimationFrame(() => pick(room.id));
}

function pick(id, printer = null, zoom = true, record = true) {
  state.picked = id;
  state.printer = printer;
  render();
  openBadges();
  const room = id && rooms().find((r) => r.id === id);
  if (room && zoom) {
    const spots = layout(room);
    if (spots.length) {
      const x0 = Math.min(...spots.map((s) => s.x)), y0 = Math.min(...spots.map((s) => s.y));
      const x1 = Math.max(...spots.map((s) => s.x)), y1 = Math.max(...spots.map((s) => s.y));
      const m = SIZE * 6;
      const box = { x: x0 - m, y: y0 - m, w: x1 - x0 + m * 2, h: y1 - y0 + m * 2 };
      if (phone.matches) {
        svg.scrollIntoView({ block: "start" });
        box.h *= 2;
      }
      vp.touch();
      vp.frameRect(box, true, 2.5);
    }
  }
  if (record) recordView();
}

function setFloor(id) {
  if (id === state.floor) {
    if (state.mode !== "list") return;
    id = null;
  }
  state.floor = id;
  state.picked = null;
  state.printer = null;
  state.drawn = null;
  render();
  recordView();
}

document.getElementById("floors").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) setFloor(b.dataset.id);
});
document.getElementById("floors").addEventListener("keydown", (e) => {
  if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
  const ids = state.status.floors.map((f) => f.id);
  const i = ids.indexOf(state.floor) + (e.key === "ArrowRight" ? 1 : -1);
  if (ids[i]) { setFloor(ids[i]); document.querySelector(`#floors [data-id="${ids[i]}"]`)?.focus(); }
});
for (const [id, key] of [["audience", "audience"], ["mode", "mode"]]) {
  document.getElementById(id).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    // Students and Staff filter; pressing the one already on shows every printer again.
    const off = key === "audience" && state.audience === b.dataset.v;
    state[key] = off ? "all" : b.dataset.v;
    for (const x of e.currentTarget.querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b && !off));
    if (key === "mode") state.drawn = null;
    render(); recordView();
  });
}
document.getElementById("zoom-in").onclick = () => { vp.touch(); vp.zoomAt(1.25, undefined, undefined, true); };
document.getElementById("zoom-out").onclick = () => { vp.touch(); vp.zoomAt(0.8, undefined, undefined, true); };
document.getElementById("zoom-level").onclick = () => vp.home();
svg.addEventListener("click", (e) => {
  if (vp.wasDrag()) return;
  const g = e.target.closest(".printer-g, .space, .badge");
  pick(g ? g.dataset.id : null, g?.dataset.printer ?? null, !!g);
});
const hover = (e) => {
  const id = e.target.closest?.(".space, .badge")?.dataset.id ?? null;
  if (id !== state.hover) { state.hover = id; openBadges(); }
};
content.addEventListener("pointerover", hover);
content.addEventListener("focusin", hover);
svg.addEventListener("pointerleave", () => { state.hover = null; openBadges(); });
svg.addEventListener("keydown", (e) => {
  const g = e.target.closest?.(".printer-g");
  if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); e.stopPropagation(); pick(g.dataset.id, g.dataset.printer); }
  if (e.key === "Escape") pick(null, null, false);
});

(async () => {
  readView();
  await Pulse.shell({ current: "printers", compact: true, title: "Printer Status", context: "Printers across campus" });
  const toolbar = document.querySelector(".map-toolbar"); toolbar.classList.add("share-scope"); toolbar.append(Pulse.copyLink(() => printerURL(), "this view"));
  let first = true;
  Pulse.poll(async () => {
    state.status = await fetch("api/status").then((r) => r.json());
    render();
    if (first && state.picked) requestAnimationFrame(() => pick(state.picked, state.printer, true, false));
    if (first) { recordView(false); if (state.mode === "list") document.querySelector("#list-view .printer-row.picked")?.scrollIntoView({ block: "nearest" }); }
    first = false;
  }, 15000);
})();

Pulse.masonry(document.getElementById("spaces"));
