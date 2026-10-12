const NS = "http://www.w3.org/2000/svg";
const WORD = { available: "free", possibly_free: "possibly free", in_use: "in use", offline: "off or not reporting",
  out_of_service: "out of service" };
const KIND = { lab: "Lab", station: "Station", kiosk: "Kiosk", podium: "Podium" };
const ORDER = ["available", "possibly_free", "in_use", "offline", "out_of_service"];

const state = { floor: null, platform: "all", mode: "map", picked: null, status: null, drawn: null };
const svg = document.getElementById("map");
const content = document.getElementById("content");
const vp = Pulse.viewport(svg, content, {
  onChange: (k) => {
    document.getElementById("zoom-level").textContent = `${Math.round(k * 100)}%`;
    svg.classList.toggle("far", k < 0.45);
    placeBadges(k);
  },
});

// Room labels keep one size on screen whatever the zoom, and a label that would cover a
// bigger room's label is hidden until there is room for it.
function placeBadges(k = vp.k) {
  const shown = [];
  const badges = [...content.querySelectorAll(".badge")].sort((a, b) => b.dataset.seats - a.dataset.seats);
  for (const b of badges) {
    b.setAttribute("transform", `translate(${b.dataset.x},${b.dataset.y}) scale(${1 / k})`);
    const w = +b.dataset.w, h = +b.dataset.h;
    const box = { x: b.dataset.x * k, y: b.dataset.y * k - h, w, h };
    const clash = shown.some((o) => box.x < o.x + o.w && o.x < box.x + box.w && box.y < o.y + o.h && o.y < box.y + box.h);
    b.style.display = clash ? "none" : "";
    if (!clash) shown.push(box);
  }
}

const el = (name, attrs = {}, parent) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  parent?.append(node);
  return node;
};
const seatsOf = (space) => space.seats.filter((s) => state.platform === "all" || s.platform === state.platform);
const countsOf = (seats) => Object.fromEntries(ORDER.map((k) => [k, seats.filter((s) => s.state === k).length]));
const shortName = (host) => (host.match(/(\d+|[A-Z])$/) || [, host.slice(-2)])[1];
const countsLine = (c) => ["in_use", "possibly_free", "offline", "out_of_service"]
  .filter((k) => c[k]).map((k) => `<b>${c[k]}</b> ${WORD[k]}`).join(" · ") || "Every seat is free";

function bounds(space) {
  if (space.box) {
    const [x0, y0, x1, y1] = space.box;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  const half = (space.seatSize || 20) / 2 + 8;
  const xs = space.seats.filter((s) => "x" in s);
  if (!xs.length) return { x: space.label[0] - 40, y: space.label[1] - 20, w: 80, h: 40 };
  const x0 = Math.min(...xs.map((s) => s.x)) - half, x1 = Math.max(...xs.map((s) => s.x)) + half;
  const y0 = Math.min(...xs.map((s) => s.y)) - half, y1 = Math.max(...xs.map((s) => s.y)) + half;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function floorSpaces(id) {
  return state.status.spaces.filter((s) => s.floor === id && seatsOf(s).length);
}

function renderFloors() {
  const tabs = document.getElementById("floors");
  tabs.replaceChildren(...state.status.floors.map((f) => {
    const seats = floorSpaces(f.id).flatMap(seatsOf);
    const b = document.createElement("button");
    b.type = "button";
    b.role = "tab";
    b.dataset.id = f.id;
    b.setAttribute("aria-selected", String(f.id === state.floor));
    b.innerHTML = `${f.name}<small>${seats.filter((s) => s.state === "available").length} free of ${seats.length}</small>`;
    return b;
  }));
}

function drawFloor() {
  const floor = state.status.floors.find((f) => f.id === state.floor);
  if (!floor) return;
  if (state.drawn !== floor.id) {
    content.replaceChildren();
    el("image", { href: `catalog/${floor.plan}`, width: floor.width, height: floor.height, class: "plan" }, content);
    el("g", { id: "spaces-layer" }, content);
    state.drawn = floor.id;
    vp.setHome({ x: 0, y: 0, w: floor.width, h: floor.height });
  }
  const layer = document.getElementById("spaces-layer");
  layer.replaceChildren();
  const labels = el("g", { class: "labels" });
  const font = 13;
  for (const space of floorSpaces(floor.id)) {
    const seats = seatsOf(space);
    const c = countsOf(seats);
    const r = bounds(space);
    const g = el("g", { class: `space${c.available ? "" : " none"}${state.picked === space.id ? " picked" : ""}`,
      role: "button", tabindex: 0, "data-id": space.id,
      "aria-label": `${space.name}, room ${space.room ?? ""}: ${c.available} of ${seats.length} free` }, layer);
    el("rect", { x: r.x, y: r.y, width: r.w, height: r.h, rx: 4, class: "room" }, g);
    const size = space.seatSize || 20;
    for (const s of seats) {
      if (!("x" in s)) continue;
      const seat = el("rect", { x: s.x - size / 2, y: s.y - size / 2, width: size, height: size, rx: size / 6,
        class: `seat ${s.state}` }, g);
      el("title", {}, seat).textContent = `${s.hostname}: ${WORD[s.state]}`;
      el("text", { x: s.x, y: s.y + 0.5, class: `num ${s.state}`, "font-size": size * 0.45 }, g).textContent = shortName(s.hostname);
    }
    const badge = el("g", { class: "badge", "data-x": r.x, "data-y": r.y - 4, "data-seats": seats.length,
      "data-id": space.id }, labels);
    const text = el("text", { x: 7, y: -7, "font-size": font }, badge);
    el("tspan", {}, text).textContent = `${space.name} `;
    el("tspan", { class: "free" }, text).textContent = `${c.available}/${seats.length} free`;
  }
  layer.append(labels);
  for (const badge of labels.children) {
    const bb = badge.firstChild.getBBox();
    badge.prepend(el("rect", { x: 0, y: bb.y - 4, width: bb.width + 14, height: bb.height + 8, rx: 3 }));
    badge.dataset.w = bb.width + 14;
    badge.dataset.h = bb.height + 8;
  }
  placeBadges();
}

function renderList() {
  const cards = state.status.spaces
    .filter((s) => (!state.floor || s.floor === state.floor) && seatsOf(s).length)
    .map((space) => {
      const seats = seatsOf(space);
      const c = countsOf(seats);
      const card = document.createElement("article");
      card.className = "card space-card";
      card.innerHTML = `<div class="head"><div><p class="kicker"></p><h3></h3></div>
        <p class="free"><b>${c.available}</b><span>free of ${seats.length}</span></p></div>
        <p class="counts">${countsLine(c)}</p><ul class="tiles"></ul>`;
      card.querySelector(".kicker").textContent = [space.room, KIND[space.kind]].filter(Boolean).join(" · ");
      card.querySelector("h3").textContent = space.name;
      card.querySelector(".tiles").replaceChildren(...seats.map(tile));
      return card;
    });
  document.getElementById("spaces").replaceChildren(...cards);
}

function tile(s) {
  const li = document.createElement("li");
  li.className = `tile ${s.state}`;
  li.textContent = shortName(s.hostname);
  li.title = `${s.hostname}: ${WORD[s.state]}. Last heard ${Pulse.ago(s.lastSeen)}`;
  li.setAttribute("aria-label", `${s.hostname}, ${WORD[s.state]}`);
  return li;
}

function renderDrawer() {
  const drawer = document.getElementById("drawer");
  const space = state.status.spaces.find((s) => s.id === state.picked);
  if (!space || state.mode !== "map") {
    drawer.hidden = true;
    return;
  }
  const seats = seatsOf(space);
  const c = countsOf(seats);
  const floor = state.status.floors.find((f) => f.id === space.floor);
  drawer.hidden = false;
  drawer.innerHTML = `<div class="head"><div><p class="kicker"></p><h3></h3></div>
      <button type="button" class="close" aria-label="Close details">Close</button></div>
    <p class="big">${c.available}</p><p class="of">free of ${seats.length}</p>
    <p class="counts">${countsLine(c)}</p>
    <ul class="tiles"></ul><h4>Seats</h4><ul class="rows"></ul>`;
  drawer.querySelector(".kicker").textContent = [floor?.name, space.room, KIND[space.kind]].filter(Boolean).join(" · ");
  drawer.querySelector("h3").textContent = space.name;
  drawer.querySelector(".tiles").replaceChildren(...seats.map(tile));
  drawer.querySelector(".rows").replaceChildren(...seats.map((s) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="host"></span><span class="state"><span class="key ${s.state}"></span>${WORD[s.state]}</span>`;
    li.querySelector(".host").textContent = s.hostname;
    return li;
  }));
  drawer.querySelector(".close").onclick = () => pick(null);
}

function render() {
  if (!state.status) return;
  if (!state.floor || !state.status.floors.some((f) => f.id === state.floor)) state.floor = state.status.floors[0]?.id ?? null;
  renderFloors();
  const seats = state.status.spaces.flatMap(seatsOf);
  document.getElementById("total").innerHTML =
    `<b>${seats.filter((s) => s.state === "available").length}</b> free of ${seats.length} on campus`;
  document.getElementById("map-view").hidden = state.mode !== "map";
  document.getElementById("list-view").hidden = state.mode !== "list";
  if (state.mode === "map") drawFloor();
  else renderList();
  renderDrawer();
}

function pick(id, zoom = true) {
  state.picked = id;
  render();
  const space = state.status.spaces.find((s) => s.id === id);
  if (space && zoom) {
    const r = bounds(space);
    const m = Math.max(r.w, r.h) * 0.6;
    vp.touch();
    vp.frameRect({ x: r.x - m, y: r.y - m, w: r.w + m * 2, h: r.h + m * 2 });
  }
  try { history.replaceState(null, "", `#floor=${state.floor}${id ? `&room=${id}` : ""}`); } catch {}
}

function setFloor(id) {
  if (id === state.floor) return;
  state.floor = id;
  state.picked = null;
  state.drawn = null;
  render();
  try { history.replaceState(null, "", `#floor=${id}`); localStorage.setItem("pulse.floor", id); } catch {}
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
for (const [id, key] of [["platform", "platform"], ["mode", "mode"]]) {
  document.getElementById(id).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state[key] = b.dataset.v;
    for (const x of e.currentTarget.querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b));
    if (key === "mode") state.drawn = null;
    render();
  });
}
document.getElementById("zoom-in").onclick = () => { vp.touch(); vp.zoomAt(1.25, undefined, undefined, true); };
document.getElementById("zoom-out").onclick = () => { vp.touch(); vp.zoomAt(0.8, undefined, undefined, true); };
document.getElementById("zoom-level").onclick = () => vp.home();
svg.addEventListener("click", (e) => {
  if (vp.wasDrag()) return;
  const g = e.target.closest(".space, .badge");
  pick(g ? g.dataset.id : null, !!g);
});
svg.addEventListener("keydown", (e) => {
  const g = e.target.closest?.(".space");
  if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); e.stopPropagation(); pick(g.dataset.id); }
  if (e.key === "Escape") pick(null, false);
});

(async () => {
  const hash = new URLSearchParams(location.hash.slice(1));
  try { state.floor = hash.get("floor") || localStorage.getItem("pulse.floor"); } catch { state.floor = hash.get("floor"); }
  const room = hash.get("room");
  await Pulse.shell({ current: "computers", context: "Shared computers across campus" });
  let first = true;
  Pulse.poll(async () => {
    state.status = await fetch("api/status").then((r) => r.json());
    render();
    if (first && room) requestAnimationFrame(() => pick(room));
    first = false;
  }, 15000);
})();
