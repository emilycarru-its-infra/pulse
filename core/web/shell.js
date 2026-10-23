// The shared masthead: the theme's logo, the site name, a context line and the product links.
// Pages call Pulse.shell({ current, context, title }) once and get the theme's brand back; title
// replaces the site name in the heading, as in "Computers Availability".

window.Pulse = window.Pulse || {};

Pulse.shell = async function ({ current, context, title, hideCurrent = false, hideOverview = false, compact = false }) {
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
  header.className = compact ? "masthead compact" : "masthead";
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
  const productIcons = {
    computers: "M3 4h18v12H3z M8 21h8 M12 16v5",
    software: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
    printers: "M7 8V3h10v5 M7 17H3V9h18v8h-4 M7 14h10v7H7z",
    servers: "M4 4h16v6H4z M4 14h16v6H4z M8 7h.01 M8 17h.01",
    websites: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18z M3 12h18 M12 3c3 3 3 15 0 18 M12 3c-3 3-3 15 0 18",
    public: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6z",
  };
  const productLabel = (node, product) => {
    const label = document.createElement("span"); label.className = "nav-label";
    label.textContent = product.title; node.append(label);
    if (!productIcons[product.id]) return;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8"); svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("class", "nav-icon");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", productIcons[product.id]); svg.append(path); node.prepend(svg);
    node.classList.add("has-icon"); node.setAttribute("aria-label", product.title); node.title = product.title;
  };
  for (const p of items) {
    if (hideOverview && p.id === "hub") continue;
    if (hideCurrent && p.id === current) continue;
    if (p.soon || !p.href) {
      // Named but not linked: the product is coming and has nothing to show yet.
      const span = document.createElement("span");
      span.className = p.soon ? "soon" : "unavailable";
      span.setAttribute("aria-disabled", "true");
      productLabel(span, p);
      if (p.soon) {
        const note = document.createElement("small");
        note.textContent = "Coming soon";
        span.append(note);
      }
      span.title = `${p.title} · ${p.soon ? "Coming soon" : "Not available"}`;
      span.setAttribute("aria-label", span.title);
      menu.append(span);
      continue;
    }
    const a = document.createElement("a");
    a.href = p.href;
    productLabel(a, p);
    if (p.id === current) a.setAttribute("aria-current", "page");
    menu.append(a);
  }
  if (menu.childElementCount) header.append(menu);
  header.append(Pulse.accessControl());

  const band = document.createElement("div");
  band.className = "band";
  band.setAttribute("aria-hidden", "true");
  const main = document.querySelector("main.doc");
  if (compact) {
    main.classList.add("product-page");
    const heading = document.createElement("div"); heading.className = "masthead-wrap";
    heading.append(header, band); main.prepend(heading);
  } else main.prepend(header, band);
  return brand;
};

// Audience descriptions are deployment data, not an authorization decision.
Pulse.accessControl = function () {
  const control = document.createElement("div");
  control.className = "page-access";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "access-trigger";
  button.setAttribute("aria-label", "Who has access to this page?");
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", "page-access-panel");
  button.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></svg>';
  const panel = document.createElement("section");
  panel.id = "page-access-panel";
  panel.className = "access-panel";
  panel.hidden = true;
  panel.setAttribute("aria-labelledby", "page-access-heading");
  const heading = document.createElement("h2");
  heading.id = "page-access-heading";
  heading.textContent = "Who has access to this page?";
  const content = document.createElement("div");
  content.className = "access-content";
  panel.append(heading, content);
  control.append(button, panel);
  let loaded = false, pinned = false, suppressed = false;
  const paragraph = (text, parent = content) => {
    const p = document.createElement("p"); p.textContent = text; parent.append(p);
  };
  const load = async () => {
    if (loaded) return;
    loaded = true;
    content.setAttribute("aria-busy", "true");
    paragraph("Loading access information…");
    try {
      const response = await fetch("/access.json", { cache: "no-cache" });
      if (!response.ok) throw new Error("Access information unavailable");
      const access = await response.json();
      if (!access.summary || !Array.isArray(access.groups)) throw new Error("Invalid audience");
      content.replaceChildren();
      paragraph(access.summary);
      for (const group of access.groups) {
        if (!group.name) continue;
        const members = Array.isArray(group.members) ? group.members : [];
        const row = document.createElement(members.length ? "details" : "div");
        row.className = "access-group";
        const label = document.createElement(members.length ? "summary" : "h3");
        label.textContent = group.name;
        row.append(label);
        if (group.description) paragraph(group.description, row);
        if (members.length) {
          const list = document.createElement("ul");
          for (const name of members) {
            const li = document.createElement("li"); li.textContent = name; list.append(li);
          }
          row.append(list);
        }
        content.append(row);
      }
      if (access.generated_at && access.groups.some((g) => g.members?.length)) {
        const date = new Date(access.generated_at);
        if (!Number.isNaN(date.getTime())) {
          paragraph(`Member lists updated ${date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}.`);
          content.lastElementChild.className = "access-updated";
        }
      }
    } catch {
      content.replaceChildren();
      paragraph("Access information is unavailable. Sign-in requirements are set by this site's administrator.");
      loaded = false;
    } finally { content.removeAttribute("aria-busy"); }
  };
  const show = () => {
    if (panel.hidden) panel.querySelectorAll("details").forEach((group) => { group.open = false; });
    panel.hidden = false; button.setAttribute("aria-expanded", "true"); load();
  };
  const close = () => {
    panel.hidden = true; pinned = false; button.setAttribute("aria-expanded", "false");
  };
  control.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "mouse" && !suppressed) show();
  });
  control.addEventListener("pointerleave", () => {
    suppressed = false;
    if (!pinned && !control.contains(document.activeElement)) close();
  });
  control.addEventListener("focusin", () => { if (!suppressed) show(); });
  control.addEventListener("focusout", (event) => {
    if (!control.contains(event.relatedTarget)) { close(); suppressed = false; }
  });
  button.addEventListener("click", () => {
    if (pinned) { close(); suppressed = true; }
    else { pinned = true; suppressed = false; show(); }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!control.contains(event.target)) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || panel.hidden) return;
    const restoreFocus = control.contains(document.activeElement);
    close(); suppressed = true;
    if (restoreFocus) { event.preventDefault(); button.focus(); }
  });
  return control;
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

// Product links encode view state, never the current authentication URL or browser history.
Pulse.linkURL = function (values, hash = false) {
  const url = new URL(location.pathname, location.origin);
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== null && value !== undefined && value !== "" && value !== false) params.set(key, value);
  if (hash) url.hash = params.toString(); else url.search = params.toString();
  return url.href;
};
Pulse.copyLink = function (getURL, name = "view") {
  const button = document.createElement("button");
  button.type = "button"; button.className = "copy-link"; button.dataset.action = "copy";
  const label = `Copy link to ${name}`;
  button.title = label; button.setAttribute("aria-label", label);
  button.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
  button.addEventListener("click", async (event) => {
    event.preventDefault(); event.stopPropagation();
    let message;
    try { await navigator.clipboard.writeText(getURL()); message = "Link copied"; }
    catch { message = "Could not copy link"; }
    button.title = message; button.setAttribute("aria-label", message);
    let status = document.getElementById("link-copy-status");
    if (!status) { status = document.createElement("span"); status.id = "link-copy-status"; status.className = "sr-only"; status.setAttribute("role", "status"); document.body.append(status); }
    status.textContent = message;
    setTimeout(() => { if (button.isConnected) { button.title = label; button.setAttribute("aria-label", label); } }, 2000);
  });
  return button;
};
