const NS = "http://www.w3.org/2000/svg";
const WORD = { available: "free", in_use: "in use", offline: "off or not reporting",
  out_of_service: "out of service" };
const KIND = { lab: "Lab", station: "Station", kiosk: "Kiosk", podium: "Podium" };
const ORDER = ["available", "in_use", "offline", "out_of_service"];

const state = { query: "", classroom: false, floor: null, platform: "all", mode: "list", picked: null, hover: null, status: null, drawn: null };
const phone = window.matchMedia("(max-width: 700px)");
const svg = document.getElementById("map");
const content = document.getElementById("content");
const vp = Pulse.viewport(svg, content, {
  onChange: (k) => {
    document.getElementById("zoom-level").textContent = `${Math.round(k * 100)}%`;
    svg.classList.toggle("far", k < 0.45);
    placeBadges(k);
    sizeHandles(k);
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
const seatsOf = (space) => space.seats.filter((s) => state.platform === "all" || s.platform === state.platform);
const matchesSpace = (space) => (!state.classroom || space.tags?.includes("classroom")) &&
  state.query.trim().toLowerCase().split(/\s+/).every((word) =>
    [space.name, space.room, KIND[space.kind], ...seatsOf(space).map((s) => `${seatName(s)} ${s.hostname}`)]
      .join(" ").toLowerCase().includes(word));
const visibleSpaces = () => state.status.spaces.filter((s) => matchesSpace(s) && seatsOf(s).length);
const mobileHint = (s) => s.mobile ? ". Mobile device; often powered off" : "";
const countsOf = (seats) => Object.fromEntries(ORDER.map((k) => [k, seats.filter((s) => s.state === k).length]));
// A seat is shown by the inventory's name for it ("FMSA Control Room") when it has one, else
// by its hostname.
const seatName = (s) => s.name || s.hostname;
// The short label on a tile: a trailing number or letter, else a name's initials.
const shortName = (text) => {
  const tail = text.match(/(\d+|\b[A-Z])$/);
  if (tail) return tail[1];
  const words = text.split(/[\s_-]+/).filter(Boolean);
  return words.length > 1 ? words.slice(0, 3).map((w) => w[0].toUpperCase()).join("") : text.slice(-2).toUpperCase();
};

// Seat labels for one space: each seat name's trailing number, or, where two seats would share
// one, the seats numbered in order. The full name is in the tooltip and the drawer.
function labelsFor(seats) {
  const short = seats.map((s) => shortName(seatName(s)));
  const clash = new Set(short).size !== short.length;
  return new Map(seats.map((s, i) => [s.hostname, clash ? String(i + 1).padStart(2, "0") : short[i]]));
}
const countsLine = (c) => ["in_use", "offline", "out_of_service"]
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
  return visibleSpaces().filter((s) => s.floor === id);
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
    const name = f.name.replace(/ Floor$/, '<span class="word"> Floor</span>');
    b.innerHTML = `${name}<small>${seats.filter((s) => s.state === "available").length}<span class="tight"> free</span><span class="word"> of ${seats.length}</span></small>`;
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
    tintPlan();
    state.drawn = floor.id;
    const home = homeFor(floor);
    // A phone's map is as tall as the floor's rooms need at full width, so no empty bands.
    svg.style.height = phone.matches
      ? `${Math.round(Math.min(Math.max(svg.clientWidth * home.h / home.w + 48, 220), innerHeight * 0.62))}px` : "";
    vp.setHome(home);
  }
  const layer = document.getElementById("spaces-layer");
  const focused = document.activeElement?.closest?.(".seat-g")?.dataset.host;
  layer.replaceChildren();
  const labels = el("g", { class: "labels" });
  const font = phone.matches ? 11 : 13;
  const roomHits = new Set();
  for (const space of floorSpaces(floor.id)) {
    const seats = seatsOf(space);
    const c = countsOf(seats);
    const r = bounds(space);
    const g = el("g", { class: `space${c.available ? "" : " none"}${state.picked === space.id ? " picked" : ""}`,
      role: "button", tabindex: 0, "data-id": space.id,
      "aria-label": `${space.name}, room ${space.room ?? ""}: ${c.available} of ${seats.length} free` }, layer);
    const roomKey = space.room || space.id;
    // Several inventory groups can share a room. A later background must not cover
    // the earlier group's seat targets; its own seats still select that group.
    el("rect", { x: r.x, y: r.y, width: r.w, height: r.h, rx: 4, class: "room",
      "pointer-events": roomHits.has(roomKey) ? "none" : "auto" }, g);
    roomHits.add(roomKey);
    const size = space.seatSize || 20;
    const names = labelsFor(seats);
    for (const s of seats) {
      if (!("x" in s)) continue;
      const one = el("g", { class: "seat-g", transform: `translate(${s.x},${s.y})`, "data-host": s.hostname }, g);
      if (edit.on) Object.assign(one, { tabIndex: 0 }).setAttribute("aria-label", `Seat ${seatName(s)}`);
      const seat = el("rect", { x: -size / 2, y: -size / 2, width: size, height: size, rx: size / 6,
        class: `seat ${s.state}` }, one);
      el("title", {}, seat).textContent = `${seatName(s)}: ${WORD[s.state]}${mobileHint(s)}`;
      if (s.mobile) for (const x of [-size * 0.28, size * 0.28]) {
        el("circle", { cx: x, cy: size * 0.54, r: size * 0.11,
          "stroke-width": size * 0.05, class: "wheel" }, one);
        el("circle", { cx: x, cy: size * 0.54, r: size * 0.025, class: "wheel-hub" }, one);
      }
      const label = names.get(s.hostname);
      el("text", { y: 0.5, class: `num ${s.state}`, "font-size": size * (label.length > 2 ? 0.32 : 0.45) }, one).textContent = label;
    }
    // A badge shows the room number; hovering or picking the room opens it to the full name.
    const badge = el("g", { class: `badge${c.available ? "" : " none"}`, "data-x": r.x, "data-y": r.y - 4, "data-seats": seats.length,
      "data-id": space.id }, labels);
    const faces = [["short", [[space.room || space.name]]], ["long", [[`${space.name} `], [`${c.available}/${seats.length} free`, "free"]]]];
    for (const [face, parts] of faces) {
      const text = el("text", { x: 7, y: -7, "font-size": font }, el("g", { class: face }, badge));
      for (const [words, cls] of parts) el("tspan", cls ? { class: cls } : {}, text).textContent = words;
    }
  }
  layer.append(labels);
  drawHandles(layer);
  if (focused) layer.querySelector(`.seat-g[data-host="${CSS.escape(focused)}"]`)?.focus();
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

// The hovered and the picked room show their full names, drawn above every other label.
function openBadges() {
  for (const b of content.querySelectorAll(".badge")) {
    const open = b.dataset.id === state.hover || b.dataset.id === state.picked;
    b.classList.toggle("open", open);
    if (open) b.parentNode.append(b);
  }
}

// On a phone a floor opens on its rooms rather than the whole plan, which is too small to read.
function homeFor(floor) {
  const spaces = floorSpaces(floor.id);
  if (!phone.matches || !spaces.length) return { x: 0, y: 0, w: floor.width, h: floor.height };
  const rs = spaces.map(bounds);
  const x0 = Math.min(...rs.map((r) => r.x)), y0 = Math.min(...rs.map((r) => r.y));
  const x1 = Math.max(...rs.map((r) => r.x + r.w)), y1 = Math.max(...rs.map((r) => r.y + r.h));
  const m = Math.max(x1 - x0, y1 - y0) * 0.05;
  return { x: x0 - m, y: y0 - m, w: x1 - x0 + m * 2, h: y1 - y0 + m * 2 };
}

// The list has one card per space name on the floor, so a lab or a set of stations spread over
// several rooms reads as one place; the rooms are named on the card and above their seats.
// Cards with the most free seats come first, then by room number; inside a card the biggest
// room comes first.
const roomsLine = (rooms) => rooms.length <= 3 ? rooms.join(" · ") : `${rooms[0]} +${rooms.length - 1} rooms`;

function renderList() {
  const groups = new Map();
  for (const space of visibleSpaces()) {
    if ((state.floor && space.floor !== state.floor) || !seatsOf(space).length) continue;
    const key = `${space.floor}|${space.name}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(space);
  }
  const cards = [...groups.values()]
    .map((spaces) => {
      spaces.sort((a, b) => seatsOf(b).length - seatsOf(a).length || (a.room ?? "").localeCompare(b.room ?? ""));
      const seats = spaces.flatMap(seatsOf);
      return { spaces, seats, c: countsOf(seats), rooms: spaces.map((s) => s.room).filter(Boolean) };
    })
    .sort((a, b) => b.c.available - a.c.available || (a.rooms[0] ?? "").localeCompare(b.rooms[0] ?? ""))
    .map(({ spaces, seats, c, rooms }) => {
      const card = document.createElement("article");
      card.className = "card space-card";
      card.innerHTML = `<div class="head"><div><h3></h3><p class="room"></p><div class="metadata"><p class="kicker"></p></div></div>
        <p class="free"><b>${c.available}</b><span>free of ${seats.length}</span></p></div>
        <p class="counts">${countsLine(c)}</p><div class="seats"></div>`;
      card.querySelector(".room").textContent = roomsLine(rooms);
      card.querySelector("h3").textContent = spaces[0].name;
      const floorName = state.floor ? null : state.status.floors.find((f) => f.id === spaces[0].floor)?.name;
      card.querySelector(".kicker").textContent = [floorName, KIND[spaces[0].kind]].filter(Boolean).join(" · ");
      const mapped = spaces.find((s) => s.floor && s.label);
      if (mapped) {
        const go = document.createElement("button");
        go.type = "button";
        go.className = "on-map";
        go.setAttribute("aria-label", `Show ${spaces[0].name} on map`);
        go.title = `Show ${spaces[0].name} on map`;
        go.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3Z M9 3v15 M15 6v15"/></svg>';
        go.onclick = () => showOnMap(mapped);
        card.querySelector(".metadata").append(go);
      }
      card.querySelector(".seats").replaceChildren(...spaces.filter((s) => seatsOf(s).length).flatMap((space) => {
        const own = seatsOf(space);
        const names = labelsFor(own);
        const tiles = document.createElement("ul");
        tiles.className = "tiles";
        tiles.replaceChildren(...own.map((s) => tile(s, names)));
        if (spaces.length === 1) return [tiles];
        const group = document.createElement("div");
        group.className = "room-seats";
        group.innerHTML = `<p class="seat-room"></p>`;
        group.firstChild.textContent = space.room ?? "";
        group.append(tiles);
        return [group];
      }));
      card.querySelector(".seats").classList.toggle("rooms", spaces.length > 1);
      return card;
    });
  document.getElementById("spaces").replaceChildren(...cards);
}

function tile(s, names) {
  const li = document.createElement("li");
  li.className = `tile ${s.state}${s.mobile ? " mobile" : ""}`;
  li.textContent = names.get(s.hostname);
  li.title = `${seatName(s)}: ${WORD[s.state]}. Last heard ${Pulse.ago(s.lastSeen)}${mobileHint(s)}`;
  li.setAttribute("aria-label", `${seatName(s)}, ${WORD[s.state]}${mobileHint(s)}`);
  return li;
}

function renderDrawer() {
  const drawer = document.getElementById("drawer");
  const space = state.status.spaces.find((s) => s.id === state.picked);
  if (!space || !matchesSpace(space) || !seatsOf(space).length || state.mode !== "map") {
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
    ${edit.on && state.status.editableRooms && space.room ? `<p class="edit-room">Drag the room or its corners to fit the plan.
      <button type="button" class="relayout">Lay the seats out again</button></p>` : ""}
    <h4>Seats</h4><ul class="rows"></ul>`;
  drawer.querySelector(".kicker").textContent = [floor?.name, space.room, KIND[space.kind]].filter(Boolean).join(" · ");
  drawer.querySelector("h3").textContent = space.name;
  // The map beside it already draws the seats, so the drawer lists them: each with the label
  // it carries on the map, its name and its state.
  const names = labelsFor(seats);
  drawer.querySelector(".rows").replaceChildren(...seats.map((s) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="tag ${s.state}"></span><span class="host"></span><span class="state">${WORD[s.state]}</span>`;
    li.querySelector(".tag").classList.toggle("mobile", !!s.mobile);
    li.title = mobileHint(s).replace(/^\. /, "");
    li.querySelector(".tag").textContent = names.get(s.hostname);
    li.querySelector(".host").textContent = seatName(s);
    return li;
  }));
  drawer.querySelector(".close").onclick = () => pick(null);
  const relayout = drawer.querySelector(".relayout");
  if (relayout) relayout.onclick = () => saveRoom(space, roomBox(space), { relayout: true });
}

function viewState() {
  return { mode: state.mode, floor: state.floor, picked: state.picked,
    platform: state.platform, classroom: state.classroom, query: state.query,
    scroll: document.getElementById("list-view").scrollTop };
}
function viewURL() {
  const params = new URLSearchParams({ view: state.mode });
  if (state.floor) params.set("floor", state.floor);
  if (state.picked) params.set("room", state.picked);
  if (state.platform !== "all") params.set("platform", state.platform);
  if (state.classroom) params.set("classroom", "1");
  if (state.query) params.set("q", state.query);
  return `#${params}`;
}
function rememberView() {
  history.replaceState({ pulse: viewState() }, "", location.href);
}
function recordView(push = true) {
  const method = push && location.hash !== viewURL() ? "pushState" : "replaceState";
  history[method]({ pulse: viewState() }, "", viewURL());
}
function readView() {
  const params = new URLSearchParams(location.hash.slice(1));
  return { mode: params.get("view") === "map" || (!params.has("view") && (params.has("floor") || params.has("room"))) ? "map" : "list",
    floor: params.get("floor"), picked: params.get("room"),
    platform: ["mac", "windows"].includes(params.get("platform")) ? params.get("platform") : "all",
    classroom: params.get("classroom") === "1", query: params.get("q") || "", scroll: 0 };
}
function syncControls() {
  for (const key of ["mode", "platform"]) for (const b of document.querySelectorAll(`#${key} button`))
    b.setAttribute("aria-pressed", String(b.dataset.v === state[key]));
  document.getElementById("classroom").setAttribute("aria-pressed", String(state.classroom));
  document.getElementById("filter").value = state.query;
}
function restoreView(view) {
  Object.assign(state, view);
  state.drawn = null;
  state.hover = null;
  syncControls();
  render();
  const restoreScroll = () => { document.getElementById("list-view").scrollTop = view.scroll || 0; };
  restoreScroll();
  requestAnimationFrame(() => requestAnimationFrame(restoreScroll));
  if (state.status && state.mode === "map" && state.picked) pick(state.picked, true, false);
}
window.addEventListener("popstate", (event) => restoreView(event.state?.pulse || readView()));
window.addEventListener("hashchange", () => {
  if (location.hash !== viewURL()) restoreView(readView());
});

function render() {
  if (!state.status) return;
  // The map always shows one floor; the list can show every floor at once.
  const known = state.status.floors.some((f) => f.id === state.floor);
  if (state.mode === "map" && !known) state.floor = visibleSpaces().find((s) => s.floor)?.floor ?? state.status.floors[0]?.id ?? null;
  else if (state.floor && !known) state.floor = null;
  renderFloors();
  const seats = visibleSpaces().flatMap(seatsOf);
  document.getElementById("total").innerHTML =
    `<b>${seats.filter((s) => s.state === "available").length}</b> free<span class="word"> of ${seats.length}${state.query || state.classroom || state.platform !== "all" ? " matching" : " on campus"}</span>`;
  document.getElementById("map-view").hidden = state.mode !== "map";
  document.getElementById("list-view").hidden = state.mode !== "list";
  document.querySelector(".zoom").hidden = state.mode !== "map";
  if (!state.status.editable && edit.on) {
    edit.on = false;
    document.getElementById("edit").setAttribute("aria-pressed", "false");
    svg.classList.remove("editing");
  }
  document.getElementById("edit-wrap").hidden = !state.status.editable;
  document.getElementById("room-edit-hint").hidden = !state.status.editableRooms;
  document.getElementById("hint").hidden = state.mode !== "map" || edit.on;
  document.getElementById("edit-hint").hidden = state.mode !== "map" || !edit.on;
  if (state.mode === "map") drawFloor();
  else renderList();
  renderDrawer();
  const result = document.getElementById("filter-result");
  const spaces = state.mode === "map" || state.floor ? visibleSpaces().filter((s) => s.floor === state.floor) : visibleSpaces();
  result.hidden = !!spaces.length;
  result.textContent = "No matching spaces. Clear the filter or choose another floor.";
}

function showOnMap(space) {
  rememberView();
  state.mode = "map";
  state.floor = space.floor;
  state.drawn = null;
  syncControls();
  pick(space.id, true, false);
  recordView();
  document.getElementById("map-view").scrollIntoView({ block: "start" });
}

function pick(id, zoom = true, record = true) {
  if (record) rememberView();
  state.picked = id;
  render();
  openBadges();
  const space = state.status.spaces.find((s) => s.id === id);
  if (space && zoom) {
    const r = bounds(space);
    const m = Math.max(r.w, r.h) * 0.6;
    const box = { x: r.x - m, y: r.y - m, w: r.w + m * 2, h: r.h + m * 2 };
    // On a phone the details sheet covers the lower half of the map, so bring the map to the top
    // of the screen and frame the room in the part above the sheet.
    if (phone.matches) {
      svg.scrollIntoView({ block: "start" });
      box.h *= 2;
    }
    vp.touch();
    vp.frameRect(box, true, 2.5);
  }
  if (record) recordView();
}

// Picking the floor already shown clears the filter in the list, which then shows every floor.
function setFloor(id) {
  rememberView();
  if (id === state.floor) {
    if (state.mode !== "list") return;
    id = null;
  }
  state.floor = id;
  state.picked = null;
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
for (const [id, key] of [["platform", "platform"], ["mode", "mode"]]) {
  document.getElementById(id).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    // Mac and Windows filter; pressing the one already on shows every platform again.
    rememberView();
    const off = key === "platform" && state.platform === b.dataset.v;
    state[key] = off ? "all" : b.dataset.v;
    for (const x of e.currentTarget.querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b && !off));
    if (key === "mode") { state.drawn = null; state.picked = null; }
    render();
    recordView();
  });
}
function applyFilters() {
  state.picked = null;
  state.hover = null;
  render();
  if (state.mode === "map") {
    const spaces = floorSpaces(state.floor);
    if (spaces.length && (state.query.trim() || state.classroom)) {
      const rs = spaces.map(bounds), pad = 40;
      const x = Math.min(...rs.map((r) => r.x)), y = Math.min(...rs.map((r) => r.y));
      vp.frameRect({ x: x - pad, y: y - pad,
        w: Math.max(...rs.map((r) => r.x + r.w)) - x + pad * 2,
        h: Math.max(...rs.map((r) => r.y + r.h)) - y + pad * 2 }, false, 2.5);
    } else vp.home();
  }
}
document.getElementById("filter").addEventListener("input", (e) => {
  rememberView();
  state.query = e.target.value;
  applyFilters();
  recordView(false);
});
document.getElementById("classroom").onclick = (e) => {
  rememberView();
  state.classroom = !state.classroom;
  e.currentTarget.setAttribute("aria-pressed", String(state.classroom));
  applyFilters();
  recordView();
};

document.getElementById("zoom-in").onclick = () => { vp.touch(); vp.zoomAt(1.25, undefined, undefined, true); };
document.getElementById("zoom-out").onclick = () => { vp.touch(); vp.zoomAt(0.8, undefined, undefined, true); };
document.getElementById("zoom-level").onclick = () => vp.home();
svg.addEventListener("click", (e) => {
  if (vp.wasDrag() || edit.dropped) return void (edit.dropped = false);
  if (edit.on && (e.target.closest(".seat-g, .handles") || e.target.closest(".space")?.dataset.id === state.picked)) return;
  const g = e.target.closest(".space, .badge");
  pick(g ? g.dataset.id : null, !!g);
});
const hover = (e) => {
  const id = e.target.closest?.(".space, .badge")?.dataset.id ?? null;
  if (id !== state.hover) { state.hover = id; openBadges(); }
};
content.addEventListener("pointerover", hover);
content.addEventListener("focusin", hover);
svg.addEventListener("pointerleave", () => { state.hover = null; openBadges(); });

svg.addEventListener("keydown", (e) => {
  const g = e.target.closest?.(".space");
  if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); e.stopPropagation(); pick(g.dataset.id); }
  if (e.key === "Escape") pick(null, false);
});

// The seat editor is offered only when the server authorizes saving positions.
// A seat dragged or nudged is saved a moment after it stops moving.
const edit = { on: false, drag: null, dropped: false, pending: {}, timer: 0 };
const seatOf = (host) => state.status.spaces.flatMap((sp) => sp.seats).find((s) => s.hostname === host);
const note = (text) => { document.getElementById("edit-note").textContent = text; };

// A poll that lands before a save has gone through would put the seat back where it was.
function keepMoves(status) {
  if (!state.status) return;
  for (const sp of status.spaces) for (const s of sp.seats) {
    const xy = edit.pending[s.hostname] || edit.inFlight?.[s.hostname];
    if (xy) [s.x, s.y] = xy;
  }
}

function place(g, s, x, y) {
  s.x = Math.round(x * 10) / 10;
  s.y = Math.round(y * 10) / 10;
  g.setAttribute("transform", `translate(${s.x},${s.y})`);
  if (!Object.keys(edit.pending).length) edit.pendingVersion = state.status.layoutVersion;
  edit.pending[s.hostname] = [s.x, s.y];
  clearTimeout(edit.timer);
  edit.timer = setTimeout(save, 400);
}

async function save() {
  if (edit.inFlight) return;
  const moves = edit.pending;
  const n = Object.keys(moves).length;
  if (!n) return;
  const version = edit.pendingVersion;
  edit.pending = {};
  edit.pendingVersion = undefined;
  edit.inFlight = moves;
  note("saving…");
  let saved = false;
  try {
    const headers = { "Content-Type": "application/json" };
    if (version !== undefined) headers["If-Match"] = version;
    const r = await fetch("api/positions", { method: "POST", headers, body: JSON.stringify(moves) });
    const result = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(result.error || `HTTP ${r.status}`);
    if (result.layoutVersion !== undefined) {
      state.status.layoutVersion = result.layoutVersion;
      if (edit.pendingVersion === version) edit.pendingVersion = result.layoutVersion;
    }
    note(`saved ${n} seat${n === 1 ? "" : "s"}`);
    saved = true;
  } catch (error) {
    note(`not saved: ${error.message}`);
  }
  edit.inFlight = null;
  if (!saved) await refresh().catch(() => {});
  if (Object.keys(edit.pending).length) edit.timer = setTimeout(save, 400);
}

document.getElementById("edit").onclick = (e) => {
  if (!state.status.editable) return;
  edit.on = !edit.on;
  e.currentTarget.setAttribute("aria-pressed", String(edit.on));
  svg.classList.toggle("editing", edit.on);
  render();
};

const svgPoint = (e) => new DOMPoint(e.clientX, e.clientY).matrixTransform(content.getScreenCTM().inverse());

// Room outlines: in edit mode the picked room shows a handle at each corner. Dragging the room
// moves it with its seats; dragging a corner resizes it, and the seats nobody placed are laid
// out again inside. The server saves the outline beside the seat positions.
const CORNERS = { nw: [0, 1], ne: [2, 1], sw: [0, 3], se: [2, 3] };
const roomBox = (space) => { const r = bounds(space); return [r.x, r.y, r.x + r.w, r.y + r.h]; };

function drawHandles(layer) {
  const space = edit.on && state.status.editableRooms && state.status.spaces.find((s) => s.id === state.picked && s.room && s.floor === state.floor);
  if (!space) return;
  const box = roomBox(space);
  const g = el("g", { class: "handles", "data-id": space.id }, layer);
  for (const [corner, [xi, yi]] of Object.entries(CORNERS)) {
    el("rect", { class: `handle ${corner}`, "data-corner": corner, "data-x": box[xi], "data-y": box[yi] }, g);
  }
  sizeHandles();
}

function sizeHandles(k = vp.k) {
  const size = 14 / k;
  for (const h of content.querySelectorAll(".handle")) {
    Object.entries({ x: h.dataset.x - size / 2, y: h.dataset.y - size / 2, width: size, height: size })
      .forEach(([a, v]) => h.setAttribute(a, v));
  }
}

function showBox(space, box, shift) {
  const g = content.querySelector(`.space[data-id="${CSS.escape(space.id)}"]`);
  const room = g?.querySelector(".room");
  if (room) Object.entries({ x: box[0], y: box[1], width: box[2] - box[0], height: box[3] - box[1] })
    .forEach(([a, v]) => room.setAttribute(a, v));
  for (const [corner, [xi, yi]] of Object.entries(CORNERS)) {
    const h = content.querySelector(`.handle.${corner}`);
    if (h) Object.assign(h.dataset, { x: box[xi], y: box[yi] });
  }
  sizeHandles();
  if (shift) for (const one of g?.querySelectorAll(".seat-g") ?? []) {
    const s = seatOf(one.dataset.host);
    one.setAttribute("transform", `translate(${s.x + shift[0]},${s.y + shift[1]})`);
  }
}

async function refresh() {
  const status = await fetch("api/status").then((r) => r.json());
  keepMoves(status);
  state.status = status;
  render();
}

async function saveRoom(space, box, extra = {}) {
  note("saving…");
  try {
    const r = await fetch("api/rooms", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ space: space.id, box: box.map((v) => Math.round(v * 10) / 10), ...extra }) });
    note(r.ok ? `saved room ${space.room}` : `not saved: ${(await r.json()).error}`);
  } catch {
    note("not saved: the server did not answer");
  }
  await refresh();
}

content.addEventListener("pointerdown", (e) => {
  if (!edit.on || !state.status.editableRooms || e.button !== 0 || e.target.closest(".seat-g")) return;
  const handle = e.target.closest(".handle");
  const room = e.target.classList.contains("room") && e.target.closest(".space");
  const id = handle?.parentNode.dataset.id ?? (room && room.dataset.id === state.picked ? room.dataset.id : null);
  if (!id) return;
  e.stopPropagation();
  const space = state.status.spaces.find((s) => s.id === id);
  edit.box = { id: e.pointerId, space, corner: handle?.dataset.corner, start: roomBox(space), from: svgPoint(e), box: null };
  e.target.setPointerCapture(e.pointerId);
});
content.addEventListener("pointermove", (e) => {
  const d = edit.box;
  if (!d || d.id !== e.pointerId) return;
  const p = svgPoint(e);
  const dx = p.x - d.from.x, dy = p.y - d.from.y;
  const b = [...d.start];
  if (!d.corner) { b[0] += dx; b[2] += dx; b[1] += dy; b[3] += dy; }
  else {
    const [xi, yi] = CORNERS[d.corner];
    b[xi] += dx;
    b[yi] += dy;
    if (b[2] - b[0] < 20 || b[3] - b[1] < 20) return;
  }
  d.box = b;
  d.shift = d.corner ? null : [dx, dy];
  showBox(d.space, b, d.shift);
});
const dropBox = (e) => {
  const d = edit.box;
  if (!d || d.id !== e.pointerId) return;
  edit.box = null;
  edit.dropped = !!d.box;
  if (d.box) saveRoom(d.space, d.box, d.shift ? { move: d.shift.map((v) => Math.round(v * 10) / 10) } : {});
};
content.addEventListener("pointerup", dropBox);
content.addEventListener("pointercancel", dropBox);

// Stopping the event here, on the canvas content, keeps the viewport underneath from panning.
content.addEventListener("pointerdown", (e) => {
  const g = edit.on && e.button === 0 && e.target.closest(".seat-g");
  if (!g) return;
  e.stopPropagation();
  const s = seatOf(g.dataset.host);
  const p = svgPoint(e);
  edit.drag = { g, s, id: e.pointerId, dx: s.x - p.x, dy: s.y - p.y, moved: false };
  g.setPointerCapture(e.pointerId);
  g.focus();
});
content.addEventListener("pointermove", (e) => {
  const d = edit.drag;
  if (!d || d.id !== e.pointerId) return;
  const p = svgPoint(e);
  d.moved = true;
  place(d.g, d.s, p.x + d.dx, p.y + d.dy);
});
const drop = (e) => {
  if (!edit.drag || edit.drag.id !== e.pointerId) return;
  edit.dropped = edit.drag.moved;
  edit.drag = null;
};
content.addEventListener("pointerup", drop);
content.addEventListener("pointercancel", drop);
content.addEventListener("keydown", (e) => {
  const g = edit.on && e.target.closest(".seat-g");
  const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  if (!g || !step) return;
  e.preventDefault();
  e.stopPropagation();
  const s = seatOf(g.dataset.host);
  const by = e.shiftKey ? 10 : 1;
  place(g, s, s.x + step[0] * by, s.y + step[1] * by);
});

(async () => {
  const initial = readView();
  Object.assign(state, initial);
  syncControls();
  await Pulse.shell({ current: "computers", title: "Computer Status", context: "Shared computers across campus" });
  let first = true;
  Pulse.poll(async () => {
    const status = await fetch("api/status").then((r) => r.json());
    keepMoves(status);
    state.status = status;
    if (!edit.drag && !edit.box) render();
    if (first) {
      if (state.picked) pick(state.picked, true, false);
      recordView(false);
    }
    first = false;
  }, 15000);
})();

Pulse.masonry(document.getElementById("spaces"));
