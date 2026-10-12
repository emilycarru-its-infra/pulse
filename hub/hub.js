const LEVEL = { ok: "Normal", warn: "Degraded", bad: "Down", idle: "No data" };
const ORDER = ["available", "possibly_free", "in_use", "offline", "out_of_service"];
const COLOUR = { available: "var(--ok)", possibly_free: "var(--warn)", in_use: "var(--text-primary)",
  offline: "var(--idle)", out_of_service: "var(--bad)" };

function card(p, s) {
  const el = document.createElement(p.soon ? "div" : "a");
  el.className = `card product${p.soon ? " soon" : ""}`;
  if (!p.soon) el.href = p.href;
  const chip = p.soon ? `<span class="chip idle">Coming</span>`
    : s ? `<span class="chip ${s.level}">${LEVEL[s.level]}</span>` : `<span class="chip bad">Not answering</span>`;
  el.innerHTML = `<div class="head"><h3></h3>${chip}</div><p class="line"></p><div class="meter-slot"></div><p class="about"></p>`;
  el.querySelector("h3").textContent = p.title;
  el.querySelector(".line").textContent = p.soon ? "Not yet live" : s ? s.line : "The product did not answer";
  el.querySelector(".about").textContent = p.about + (p.restricted ? " (restricted audience)" : "");
  if (s?.counts && s.seats) {
    const meter = document.createElement("div");
    meter.className = "meter";
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", ORDER.map((k) => `${s.counts[k]} ${k.replace(/_/g, " ")}`).join(", "));
    for (const k of ORDER) {
      if (!s.counts[k]) continue;
      const seg = document.createElement("span");
      seg.style.width = `${(100 * s.counts[k]) / s.seats}%`;
      seg.style.background = COLOUR[k];
      meter.append(seg);
    }
    el.querySelector(".meter-slot").replaceWith(meter);
  }
  const li = document.createElement("li");
  li.append(el);
  return li;
}

(async () => {
  await Pulse.shell({ current: "hub", context: "Live status of shared university systems" });
  const products = await fetch("/hub/products.json").then((r) => r.json());
  Pulse.poll(async () => {
    const summaries = await Promise.all(products.map((p) =>
      p.soon ? null : fetch(p.summary).then((r) => (r.ok ? r.json() : null)).catch(() => null)));
    document.getElementById("products").replaceChildren(...products.map((p, i) => card(p, summaries[i])));
    document.getElementById("updated").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }, 15000);
})();
