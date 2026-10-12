const WORD = { available: "free", possibly_free: "possibly free", in_use: "in use", offline: "off or not reporting",
  out_of_service: "out of service" };
const KIND = { lab: "Lab", station: "Open-access station", kiosk: "Kiosk", podium: "Podium" };
let platform = "all";
let last;

function shortName(host) {
  const m = host.match(/(\d+|[A-Z])$/);
  return m ? m[1] : host.slice(-2);
}

function render(status) {
  last = status;
  let free = 0, total = 0;
  const cards = status.spaces.map((space) => {
    const seats = space.seats.filter((s) => platform === "all" || s.platform === platform);
    const counts = {};
    for (const s of seats) counts[s.state] = (counts[s.state] || 0) + 1;
    free += counts.available || 0;
    total += seats.length;

    const card = document.createElement("article");
    card.className = "card space" + (seats.length ? "" : " empty-filter");
    const where = [space.building && `Building ${space.building}`, space.floor && `Floor ${space.floor}`, KIND[space.kind]]
      .filter(Boolean).join(" · ");
    card.innerHTML = `<div class="head"><div><p class="kicker"></p><h3></h3></div>
      <p class="free"><b></b><span>free of ${seats.length}</span></p></div>
      <p class="counts"></p><ul class="seats"></ul>`;
    card.querySelector(".kicker").textContent = where;
    card.querySelector("h3").textContent = space.name;
    card.querySelector(".free b").textContent = counts.available || 0;
    card.querySelector(".counts").innerHTML = ["in_use", "possibly_free", "offline", "out_of_service"]
      .filter((k) => counts[k]).map((k) => `<b>${counts[k]}</b> ${WORD[k]}`).join(" · ") || "Every seat is free";
    card.querySelector(".seats").replaceChildren(...seats.map((s) => {
      const li = document.createElement("li");
      li.className = `seat ${s.state}`;
      li.tabIndex = 0;
      li.textContent = shortName(s.hostname);
      const label = `${s.hostname}, ${s.platform === "mac" ? "Mac" : s.platform === "windows" ? "Windows" : ""}, ${WORD[s.state]}`;
      li.title = `${label}. Last heard ${Pulse.ago(s.lastSeen)}`;
      li.setAttribute("aria-label", label);
      return li;
    }));
    return card;
  });
  document.getElementById("spaces").replaceChildren(...cards);
  document.getElementById("total").innerHTML =
    `<div class="big">${free}</div><div class="of">free of ${total} ${platform === "all" ? "" : platform === "mac" ? "Mac " : "Windows "}computers</div>`;
  document.getElementById("updated").textContent = `Updated ${new Date(status.generatedAt).toLocaleTimeString()}`;
}

document.getElementById("platform").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  platform = b.dataset.v;
  for (const x of e.currentTarget.querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b));
  if (last) render(last);
});

(async () => {
  await Pulse.shell({ current: "computers", context: "Shared computers across campus" });
  Pulse.poll(async () => render(await fetch("api/status").then((r) => r.json())), 15000);
})();
