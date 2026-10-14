// The shared masthead: the theme's logo, the site name, a context line and the product links.
// Pages call Pulse.shell({ current, context, title }) once and get the theme's brand back; title
// replaces the site name in the heading, as in "Computer Status".

window.Pulse = window.Pulse || {};

Pulse.shell = async function ({ current, context, title }) {
  const brand = await fetch("/theme/brand.json").then((r) => r.json()).catch(() => ({}));
  const products = await fetch("/hub/products.json").then((r) => r.json()).catch(() => []);
  // A site may list the products its menu offers in /nav.json, each { id, title, href, soon }.
  // Without one the menu is the hub's Overview plus every product the hub lists as live.
  const nav = await fetch("/nav.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (!document.querySelector('link[rel="icon"]')) {
    const icon = document.createElement("link");
    icon.rel = "icon";
    icon.type = "image/svg+xml";
    icon.href = brand.favicon ? `/theme/${brand.favicon}` : "/core/favicon.svg";
    document.head.append(icon);
  }
  const site = brand.site || "Status";
  document.title = title ?? (current === "hub" ? site : `${products.find((p) => p.id === current)?.title ?? ""} · ${site}`);

  const header = document.createElement("header");
  header.className = "masthead";
  if (brand.logo) {
    header.insertAdjacentHTML("beforeend",
      `<img class="logo logo-light${brand.logoDark ? " has-dark" : ""}" src="/theme/${brand.logo}" alt="${brand.org ?? ""}">` +
      (brand.logoDark ? `<img class="logo logo-dark" src="/theme/${brand.logoDark}" alt="">` : ""));
  }
  const text = document.createElement("div");
  text.className = "masthead-text";
  text.innerHTML = `<h1><a href="/"></a></h1><p class="context"></p>`;
  text.querySelector("h1 a").textContent = title ?? site;
  text.querySelector(".context").textContent = context ?? "";
  header.append(text);

  const menu = document.createElement("nav");
  menu.className = "masthead-nav";
  menu.setAttribute("aria-label", "Products");
  const items = Array.isArray(nav) ? nav : [{ id: "hub", title: "Overview", href: "/" }, ...products.filter((p) => !p.soon)];
  for (const p of items) {
    if (p.soon || !p.href) {
      // Named but not linked: the product is coming and has nothing to show yet.
      const span = document.createElement("span");
      span.className = "soon";
      span.setAttribute("aria-disabled", "true");
      span.textContent = p.title;
      const note = document.createElement("small");
      note.textContent = "Coming soon";
      span.append(note);
      menu.append(span);
      continue;
    }
    const a = document.createElement("a");
    a.href = p.href;
    a.textContent = p.title;
    if (p.id === current) a.setAttribute("aria-current", "page");
    menu.append(a);
  }
  if (menu.childElementCount) header.append(menu);

  const band = document.createElement("div");
  band.className = "band";
  band.setAttribute("aria-hidden", "true");
  document.querySelector("main.doc").prepend(header, band);
  return brand;
};

Pulse.ago = function (iso) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
};

Pulse.poll = function (fn, ms) {
  let timer;
  const tick = async () => {
    try { await fn(); } catch (e) { console.error(e); }
    timer = setTimeout(tick, document.hidden ? ms * 4 : ms);
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { clearTimeout(timer); tick(); } });
  tick();
};
