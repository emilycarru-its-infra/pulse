// WebsitesPulse: an alphabetical website grid with hosting filters and inline details.

const WORD = {
  up: "Up",
  degraded: "Warning",
  down: "Error",
  unknown: "Not reporting",
};
const CHECK_WORD = { ok: "OK", warn: "Warning", down: "Error" };
const CHECK_TAG = { ok: "up", warn: "degraded", down: "down" };
const FACTS = [
  ["host", "Hosted on"],
  ["account", "Account"],
  ["php_version", "PHP"],
  ["wordpress_version", "WordPress"],
  ["plugins_vulnerable", "Vulnerable plugins and themes"],
  ["last_backup_at", "Last backup"],
  ["visits_24h", "Visits (24 hours)"],
  ["bandwidth_bytes_24h", "Server transfer"],
  ["cdn_bandwidth_bytes_24h", "CDN transfer"],
  ["disk_bytes", "Disk usage"],
  ["http_4xx_24h", "Client errors (4xx)"],
  ["http_5xx_24h", "Server errors (5xx)"],
  ["analytics_from", "Analytics from"],
  ["analytics_to", "Analytics to"],
  ["analytics_at", "Analytics collected"],
  ["http_status", "HTTP status"],
  ["response_ms", "Response time"],
];

const ui = {
  filter: "all",
  place: null,
  network: null,
  php: null,
  wordpress: null,
  query: "",
  view: "auto",
  picked: new URLSearchParams(location.hash.slice(1)).get("site"),
};
let data = null;

function readFilters() {
  const url = new URL(location.href);
  for (const [field, key] of [["place", "hosting"], ["network", "network"], ["php", "php"], ["wordpress", "wordpress"]])
    ui[field] = url.searchParams.get(key)?.slice(0, 200) || null;
  ui.query = url.searchParams.get("q")?.trim().slice(0, 500) || "";
  ui.view = ["websites", "installations"].includes(url.searchParams.get("view")) ? url.searchParams.get("view") : "auto";
  const state = url.searchParams.get("status");
  ui.filter = ["up", "degraded", "down", "unknown"].includes(state) ? state : "all";
  ui.picked = url.searchParams.get("site") || new URLSearchParams(url.hash.slice(1)).get("site");
  const search = typeof document !== "undefined" ? document.getElementById("search") : null;
  if (search) search.value = ui.query;
}
readFilters();

function websiteUrl() {
  const url = new URL(location.href);
  for (const [key, value] of [["hosting", ui.place], ["network", ui.network], ["php", ui.php], ["wordpress", ui.wordpress],
    ["view", ui.view === "auto" ? null : ui.view], ["status", ui.filter === "all" ? null : ui.filter], ["q", ui.query], ["site", ui.picked]]) {
    if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  }
  const legacy = new URLSearchParams(url.hash.slice(1));
  if (legacy.has("site")) { legacy.delete("site"); url.hash = legacy.toString(); }
  return url;
}
function writeFilters(replace = false) {
  const url = websiteUrl();
  if (url.href !== location.href) history[replace ? "replaceState" : "pushState"](null, "", url.href);
}
function hasFilters() {
  return Boolean(ui.place || ui.network || ui.php || ui.wordpress || ui.query || ui.view !== "auto" || ui.filter !== "all");
}
function clearFilters() {
  Object.assign(ui, {place:null, network:null, php:null, wordpress:null, query:"", view:"auto", filter:"all", picked:null});
}
function websiteFacts(w) { return {...(w.hosting?.facts || {}), ...(w.facts || {})}; }
function websitePlugins(w) { return w.plugin_inventory || w.hosting?.plugin_inventory; }
function pluginLocation(w) {
  const f = websiteFacts(w);
  return [hostingName(w), f.account ? `Account ${fact("account", f.account)}` : "Account not reported",
    `Installation ${w.hosting?.hostname || (w.hosting ? w.hosting.name : w.hostname) || "not reported"}`].join(" · ");
}
let searchCache = {query: null};
function searchExpression() {
  if (searchCache.query === ui.query) return searchCache;
  try {
    const tokens = [];
    const pattern = /\s*(?:"([^"]+)"|([()]|[^\s()"]+))/y;
    const query = ui.query.trim();
    while (pattern.lastIndex < query.length) {
      const token = pattern.exec(query);
      if (!token) throw new Error("Close each quoted phrase.");
      tokens.push(token[1] !== undefined ? {term: token[1].toLowerCase()} :
        /^(AND|OR|NOT|\(|\))$/i.test(token[2]) ? token[2].toUpperCase() : {term: token[2].toLowerCase()});
    }
    let index = 0;
    const unary = () => {
      const token = tokens[index++];
      if (token === "NOT") return {not: unary()};
      if (token === "(") {
        const node = or();
        if (tokens[index++] !== ")") throw new Error("Close each parenthesis.");
        return node;
      }
      if (!token || typeof token === "string") throw new Error("Add a search term after each operator.");
      return token;
    };
    const and = () => {
      let node = unary();
      while (index < tokens.length && tokens[index] !== "OR" && tokens[index] !== ")") {
        if (tokens[index] === "AND") index++;
        node = {and: [node, unary()]};
      }
      return node;
    };
    const or = () => {
      let node = and();
      while (tokens[index] === "OR") { index++; node = {or: [node, and()]}; }
      return node;
    };
    const tree = tokens.length ? or() : null;
    if (index !== tokens.length) throw new Error("Check the search parentheses and operators.");
    const positive = [];
    const terms = (node, negated = false) => {
      if (!node) return;
      if (node.term && !negated) positive.push(node.term);
      if (node.not) terms(node.not, !negated);
      for (const child of node.and || node.or || []) terms(child, negated);
    };
    terms(tree);
    searchCache = {query: ui.query, tree, positive};
  } catch (error) { searchCache = {query: ui.query, error: error.message, positive: []}; }
  return searchCache;
}
function searchMatches(node, hay) {
  if (!node) return true;
  if (node.term) return hay.includes(node.term);
  if (node.not) return !searchMatches(node.not, hay);
  return node.and ? node.and.every(child => searchMatches(child, hay)) : node.or.some(child => searchMatches(child, hay));
}
function cardPlugins(w) {
  const findings = new Map();
  for (const env of websitePlugins(w)?.environments || []) {
    for (const plugin of env.plugins || []) {
      const matched = searchExpression().positive.some(term =>
        `${plugin.title || ""} ${plugin.slug || ""} ${plugin.version || ""}`.toLowerCase().includes(term));
      if (plugin.is_version_vulnerable !== true && !matched) continue;
      const key = JSON.stringify([plugin.slug, plugin.version]);
      if (!findings.has(key)) findings.set(key, {plugin, environments: new Set(), flagged: new Set()});
      const label = env.is_live ? "Live" : env.name || "Other environment";
      findings.get(key).environments.add(label);
      if (plugin.is_version_vulnerable === true) findings.get(key).flagged.add(label);
    }
  }
  return [...findings.values()].sort((a, b) =>
    (a.plugin.title || a.plugin.slug).localeCompare(b.plugin.title || b.plugin.slug));
}
function genericPluginAlert(alert) {
  return /plugin or theme.*vulnerab|vulnerab.*plugin or theme/i.test(alert.text || "");
}
function pluginSearch(w) {
  return (websitePlugins(w)?.environments || []).flatMap(e => (e.plugins || []).map(p =>
    `${p.slug || ""} ${p.title || ""} ${p.version || ""} ${p.status || ""}`)).join(" ");
}
function renderDropdowns() {
  for (const [id, field, all, valueOf] of [["hosting", "place", "All hosting", w => w.group],
    ["network", "network", "All networks", w => w.network || "unknown"]]) {
    const select = document.getElementById(id);
    const counts = new Map();
    for (const website of data.websites) {
      const value = valueOf(website); counts.set(value, (counts.get(value) || 0) + 1);
    }
    if (ui[field] && !counts.has(ui[field])) counts.set(ui[field], 0);
    const labelOf = value => id === "hosting" ? data.groups.find(g => g.id === value)?.name || value : value === "unknown" ? "Not reported" : value;
    const other = value => /^(unknown|other|not reported|host not recorded)$/i.test(labelOf(value));
    const choices = [["", all], ...[...counts].sort(([a], [b]) => Number(other(a)) - Number(other(b)) || labelOf(a).localeCompare(labelOf(b), undefined, {numeric:true}))
      .map(([value]) => [value, labelOf(value)])];
    const signature = JSON.stringify(choices);
    if (select.dataset.choices !== signature) {
      select.replaceChildren(...choices.map(([value, label]) => {
        const option = el("option", null, label); option.value = value; return option;
      }));
      select.dataset.choices = signature;
    }
    select.value = ui[field] || "";
  }
}
function renderPicture() {
  const wrap = document.getElementById("picture");
  const focused = document.activeElement?.closest(".website-filter-tag");
  const focusKey = focused ? [focused.dataset.field, focused.dataset.value] : null;
  const configs = [["php", "php", "PHP version", w => websiteFacts(w).php_version || "unknown"],
    ["wordpress", "wordpress", "WordPress version", w => websiteFacts(w).wordpress_version || "unknown"]];
  const buttons = [];
  const groups = configs.map(([id, field, name, valueOf]) => {
    const group = el("div", "website-filter-group");
    group.setAttribute("role", "group"); group.setAttribute("aria-label", name);
    const values = new Map();
    for (const w of data.websites) {
      if (["php", "wordpress"].includes(id) && ((ui.place && w.group !== ui.place) || (ui.network && w.network !== ui.network))) continue;
      const value = valueOf(w);
      values.set(value, (values.get(value) || 0) + 1);
    }
    if (ui[field] && !values.has(ui[field])) values.set(ui[field], 0);
    const labelOf = value => id === "hosting" ? data.groups.find(g => g.id === value)?.name || value : value === "unknown" ? "Not reported" : value;
    const other = value => /^(unknown|other|not reported|host not recorded)$/i.test(labelOf(value));
    const choices = [...values].sort(([a], [b]) => Number(other(a)) - Number(other(b)) || labelOf(a).localeCompare(labelOf(b), undefined, {numeric:true}))
      .map(([value]) => [value, `${value !== "unknown" && id === "php" ? "PHP " : value !== "unknown" && id === "wordpress" ? "WordPress " : ""}${labelOf(value)}`]);
    for (const [value, label] of choices) {
      const button = el("button", "website-filter-tag"); button.type = "button";
      button.dataset.field = field; button.dataset.value = value;
      button.setAttribute("aria-pressed", String((ui[field] || "") === value));
      button.append(PulseTech.badge(label, ["php", "wordpress"].includes(id) ? id : labelOf(value), "binary"));
      button.addEventListener("click", () => {
        ui[field] = ui[field] === value ? null : value || null;
        writeFilters(); render();
      });
      buttons.push(button); group.append(button);
    }
    return group;
  });
  wrap.replaceChildren(...groups);
  if (focusKey) buttons.find(button => button.dataset.field === focusKey[0] && button.dataset.value === focusKey[1])?.focus({preventScroll:true});
}
let layoutFrame;
let layoutScroll;
function scheduleLayout(position) {
  if (typeof requestAnimationFrame !== "function") return;
  if (position && Number.isFinite(position.y)) layoutScroll = position;
  cancelAnimationFrame(layoutFrame);
  layoutFrame = requestAnimationFrame(() => {
    const list = document.getElementById("groups");
    if (!list.clientWidth) return;
    const cards = [...list.children];
    const style = getComputedStyle(list);
    const gap = parseFloat(style.columnGap);
    const minimum = parseFloat(style.getPropertyValue("--card-min-width"));
    const columns = Math.max(1, Math.floor((list.clientWidth + gap) / (minimum + gap)));
    let cursor = 0;
    const placements = cards.map(card => {
      const span = card.className === "empty-state" ? columns :
        Math.min(columns, card.firstElementChild?.getAttribute("aria-expanded") === "true" ? 2 : 1);
      if (cursor + span > columns) cursor = 0;
      const column = cursor;
      cursor = (cursor + span) % columns;
      card.style.gridColumn = `${column + 1} / span ${span}`;
      return {column, span};
    });
    const heights = Array(columns).fill(0);
    cards.forEach((card, index) => {
      const {column, span} = placements[index];
      const top = Math.max(...heights.slice(column, column + span));
      const height = Math.ceil(card.getBoundingClientRect().height);
      card.style.gridRow = `${top + 1} / span ${height}`;
      heights.fill(top + height + gap, column, column + span);
    });
    list.style.minHeight = "";
    if (layoutScroll) {
      const position = layoutScroll;
      layoutScroll = null;
      const anchor = position.anchor && document.getElementById(position.anchor.id);
      const top = anchor ? window.scrollY + anchor.getBoundingClientRect().top - position.anchor.top : position.y;
      window.scrollTo({left: position.x, top, behavior: "instant"});
    }
  });
}


function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function ago(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function fact(key, value) {
  if (value == null || value === "") return null;
  if (key.endsWith("_at") || ["analytics_from", "analytics_to"].includes(key))
    return dateTime(value);
  if (key.includes("bytes")) return dataSize(value);
  if (["visits_24h", "http_4xx_24h", "http_5xx_24h", "plugins_vulnerable"].includes(key))
    return Number(value).toLocaleString();
  if (key === "response_ms") return Number(value) >= 1000 ? `${(Number(value) / 1000).toLocaleString(undefined, {maximumFractionDigits: 2})} s` : `${Number(value).toLocaleString()} ms`;
  if (key === "account") return String(value).replace(/_/g, " ");
  return String(value);
}

function dateTime(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Not reported";
  return date.toLocaleString(undefined, {year: date.getFullYear() === new Date().getFullYear() ? undefined : "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
}

function dataSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "Not reported";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = bytes > 0 ? Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1000))) : 0;
  return `${(bytes / 1000 ** index).toLocaleString(undefined, {maximumFractionDigits: index ? 1 : 0})} ${units[index]}`;
}

function matches(w) {
  if (ui.place && w.group !== ui.place) return false;
  if (ui.network && (w.network || "unknown") !== ui.network) return false;
  if (ui.php && (websiteFacts(w).php_version || "unknown") !== ui.php) return false;
  if (ui.wordpress && (websiteFacts(w).wordpress_version || "unknown") !== ui.wordpress) return false;
  if (ui.filter !== "all" && w.state !== ui.filter) return false;
  if (!ui.query) return true;
  const f = websiteFacts(w);
  const hay =
    `${w.name} ${w.network || ""} ${w.hostname || ""} ${w.url || ""} ${w.owner || ""} ${f.php_version || ""} php${f.php_version || ""} ${f.wordpress_version || ""} ${f.account || ""} ${pluginSearch(w)}`.toLowerCase();
  const search = searchExpression();
  return !search.error && searchMatches(search.tree, hay);
}

function hostingName(w) {
  return data.groups.find((g) => g.id === w.group)?.name || w.facts?.host || "Host not recorded";
}

function installationView() {
  if (ui.view !== "auto") return ui.view === "installations";
  if (ui.php || ui.wordpress) return true;
  const terms = [];
  const visit = node => {
    if (!node) return;
    if (node.term) terms.push(node.term);
    if (node.not) visit(node.not);
    for (const child of node.and || node.or || []) visit(child);
  };
  visit(searchExpression().tree);
  return terms.some(term => data.websites.some(w =>
    pluginSearch(w).toLowerCase().includes(term) ||
    [`php ${websiteFacts(w).php_version || ""}`, `php${websiteFacts(w).php_version || ""}`,
      `wordpress ${websiteFacts(w).wordpress_version || ""}`].some(version => version.includes(term))));
}
function subsites(w) {
  return data.websites.filter(child => child.hosting?.website_id === w.id && child.id !== w.id);
}
function websiteKind(w) {
  if (w.hosting) return "WordPress subsite";
  if (subsites(w).length || websitePlugins(w)?.environments?.length || websiteFacts(w).wordpress_version)
    return "WordPress installation";
  return "Website";
}
function entryUrl(id) {
  const url = new URL(location.href);
  url.search = ""; url.hash = "";
  url.searchParams.set("site", id);
  url.searchParams.set("view", "websites");
  return url.href;
}
function visibleWebsites() {
  const matching = data.websites.filter(matches);
  let members = matching;
  if (installationView()) {
    const byId = new Map(data.websites.map(w => [w.id, w]));
    const targets = new Map();
    for (const w of matching) {
      // Only an explicit installation relationship can combine patch targets.
      const parent = byId.get(w.hosting?.website_id) || w;
      if (!targets.has(parent.id)) targets.set(parent.id, {...parent, matchingWebsites: []});
      targets.get(parent.id).matchingWebsites.push(w);
    }
    members = [...targets.values()];
  }
  // Keep explicit subsite deep links reviewable, including in installation search results.
  const picked = data.websites.find(w => w.id === ui.picked);
  if (picked && matching.some(w => w.id === picked.id) && !members.some(w => w.id === picked.id))
    members.push(picked);
  return members.sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true }) || a.id.localeCompare(b.id));
}
function renderRelationships(w) {
  const section = el("section", "installation-relationships");
  if (w.hosting) {
    section.append(el("h4", null, "Parent installation"));
    const parent = el("a", null, w.hosting.hostname || w.hosting.name);
    parent.href = entryUrl(w.hosting.website_id);
    section.append(parent, el("p", null, "Patch shared plugin files at this parent installation in the affected environment. Subsite activation can differ; staging is patched separately."));
  } else {
    const children = subsites(w);
    if (!children.length) return section;
    section.append(el("h4", null, `WordPress subsites · ${children.length}`),
      el("p", null, "These websites share this installation’s WordPress and plugin files. Updating those files here applies to its subsites in the same environment; individual activation and exposure may differ."));
    const list = el("ul");
    for (const child of children) {
      const item = el("li");
      const link = el("a", null, `${child.name} · ${child.url || child.hostname}`);
      link.href = entryUrl(child.id); item.append(link); list.append(item);
    }
    const disclosure = el("details", "subsite-list");
    disclosure.append(el("summary", null, "Show subsite addresses"), list);
    section.append(disclosure);
  }
  return section;
}

function renderDetails(w) {
  const box = el("section", "details");
  box.id = `details-${w.id}`;
  const dl = el("dl");
  const add = (label, value) => {
    if (value) {
      const dd = el("dd");
      if (["Network", "Hosting", "Hosted on", "PHP", "WordPress"].includes(label)) dd.append(PulseTech.badge(value, ["PHP", "WordPress"].includes(label) ? label : "", "label"));
      else dd.textContent = value;
      dl.append(el("dt", null, label), dd);
    }
  };
  add("Address", w.url || w.hostname);
  add("Type", websiteKind(w));
  add("Owner", w.owner);
  add("Network", w.network);
  add("Hosting", hostingName(w));
  box.append(el("h4", null, "Website and hosting"));
  for (const [key, label] of FACTS)
    if (!key.endsWith("_24h") && !key.startsWith("analytics_") && !["http_status", "response_ms"].includes(key) &&
        !(key === "host" && String(w.facts?.host || "").toLowerCase() === hostingName(w).toLowerCase()))
      add(label, fact(key, (w.facts || {})[key]));
  box.append(dl);
  box.append(renderRelationships(w));
  const traffic = FACTS.filter(([key]) => key.endsWith("_24h") && w.facts?.[key] != null);
  if (traffic.length) {
    box.append(el("h4", null, "Traffic · past 24 hours"));
    const metrics = el("dl", "traffic-metrics");
    for (const [key, label] of traffic)
      metrics.append(el("dt", null, label.replace(" (24 hours)", "")), el("dd", null, fact(key, w.facts[key])));
    box.append(metrics);
    if (w.facts.analytics_from && w.facts.analytics_to)
      box.append(el("p", "observation-time", `${dateTime(w.facts.analytics_from)} – ${dateTime(w.facts.analytics_to)}`));
    if (w.facts.analytics_at)
      box.append(el("p", "observation-time", `Collected ${dateTime(w.facts.analytics_at)}`));
  }
  box.append(el("h4", null, "Latest check"));
  const checked = el("dl");
  for (const [key, label] of [["http_status", "HTTP status"], ["response_ms", "Response time"]])
    if (w.facts?.[key] != null) checked.append(el("dt", null, label), el("dd", null, fact(key, w.facts[key])));
  checked.append(el("dt", null, "Checked"), el("dd", null, w.lastCheck ? `${dateTime(w.lastCheck)} · ${ago(w.lastCheck)}` : "No check received"));
  box.append(checked);
  box.append(renderPlugins(w));
  if (w.hosting) {
    box.append(el("h4", null, `Shared ${w.hosting.name} hosting`));
    const shared = el("dl");
    for (const [key, label] of FACTS) {
      const value = fact(key, w.hosting.facts?.[key]);
      if (value != null) {
        const dd = el("dd");
        if (["Hosted on", "PHP", "WordPress"].includes(label)) dd.append(PulseTech.badge(value, label === "Hosted on" ? value : label, "label"));
        else dd.textContent = value;
        shared.append(el("dt", null, label), dd);
      }
    }
    box.append(shared);
    const parent = el("a", null, "View shared installation analytics");
    const parentUrl = websiteUrl();
    for (const key of ["hosting", "network", "php", "wordpress", "status", "q"]) parentUrl.searchParams.delete(key);
    parentUrl.searchParams.set("site", w.hosting.website_id);
    parent.href = parentUrl.href;
    box.append(parent);
    if (w.hosting.lastCheck) box.append(el("p", null, `Hosting reported ${ago(w.hosting.lastCheck)}`));
  }
  if (w.network && !w.hosting && w.facts?.analytics_at)
    box.append(el("p", null, `Analytics cover the whole ${w.network} network.`));
  if ((w.alerts || []).length) {
    box.append(el("h4", null, "Alerts"));
    const ul = el("ul");
    for (const a of w.alerts) {
      const li = el("li");
      li.append(
        el("span", `tag ${a.severity === "critical" ? "down" : "degraded"}`),
        el(
          "span",
          null,
          `${a.source}: ${a.text}${a.since ? ` · since ${ago(a.since)}` : ""}`,
        ),
      );
      ul.append(li);
    }
    box.append(ul);
  }
  if ((w.checks || []).length) {
    box.append(el("h4", null, "Checks"));
    const ul = el("ul");
    for (const c of w.checks) {
      const li = el("li");
      li.append(
        el("span", `tag ${CHECK_TAG[c.state]}`),
        el(
          "span",
          null,
          `${c.source} · ${CHECK_WORD[c.state]}${c.reason === "restricted" ? " · Access restricted" : c.reason === "rate-limited" ? " · Rate limited" : ""}${c.at ? ` · ${ago(c.at)}` : ""}`,
        ),
      );
      ul.append(li);
    }
    box.append(ul);
  }
  return box;
}

function renderPlugins(w) {
  const section = el("section", "plugin-inventory");
  section.append(el("h4", null, w.hosting ? "Shared installation plugins" : "Installed plugins"));
  const environments = websitePlugins(w)?.environments || [];
  if (!environments.length) {
    section.append(el("p", null, "Plugin inventory unavailable."));
    return section;
  }
  section.append(el("p", "plugin-location", `Installed WordPress plugins · ${pluginLocation(w)}`));
  if (w.hosting || environments.some(e => e.scope === "network"))
    section.append(el("p", null, "Shared network inventory. Activation shown is network or main-site status; individual subsite activation has not been collected."));
  for (const env of environments) {
    const fresh = env.collected_at && Number.isFinite(Date.parse(env.collected_at)) && Date.now() - Date.parse(env.collected_at) <= 30 * 3600000;
    const label = env.status === "complete" && fresh ? "Collected" : env.status === "complete" ? "Stale inventory" : "Incomplete inventory";
    const environmentName = env.name === "live" ? "Live" : env.name;
    section.append(el("h4", null, `${environmentName}${env.is_live && env.name !== "live" ? " · live" : ""} · ${(env.plugins || []).length} plugin${(env.plugins || []).length === 1 ? "" : "s"}`));
    const source = {"kinsta-wp-cli": "Kinsta WP-CLI", "kinsta-api": "Kinsta API"}[env.source] || env.source || "Not reported";
    section.append(el("p", "observation-time", `Source: ${source} · ${env.scope === "network" ? "Shared WordPress network" : env.scope === "installation" ? "WordPress installation" : "Scope not reported"}`));
    section.append(el("p", "observation-time", `${label}${env.collected_at ? ` · ${dateTime(env.collected_at)}` : " · no collection time"}`));
    const providerAt = Date.parse(env.provider_scanned_at);
    const providerValid = Number.isFinite(providerAt) && providerAt > 0;
    section.append(el("p", "observation-time", providerValid ? `Provider check: ${dateTime(providerAt)}${Date.now() - providerAt > 30 * 3600000 ? " · stale" : ""}` : "Provider security check unavailable"));
    const table = el("table", "plugin-table");
    table.setAttribute("aria-label", `${environmentName} installed plugins`);
    const head = el("thead");
    const headings = el("tr");
    for (const name of ["Plugin", "Version", "Activation", "Security"]) {
      const th = el("th", null, name); th.setAttribute("scope", "col"); headings.append(th);
    }
    head.append(headings); table.append(head);
    const body = el("tbody");
    const statusLabels = {active: "Active", inactive: "Inactive", "active-network": "Network active", "must-use": "Must-use", dropin: "Drop-in"};
    for (const p of [...(env.plugins || [])].sort((a,b) => (a.title || a.slug).localeCompare(b.title || b.slug))) {
      const row = el("tr", p.is_version_vulnerable === true ? "plugin-flagged" : "");
      const name = el("td", "plugin-title");
      name.append(el("span", "plugin-name", p.title || p.slug));
      if (p.title && p.title !== p.slug) name.append(el("span", "plugin-slug", p.slug));
      row.append(name, el("td", "plugin-version", p.version || "Unknown"));
      const activation = el("td");
      activation.append(el("span", `plugin-activation ${p.status === "inactive" ? "inactive" : ""}`, statusLabels[p.status] || "Unknown"));
      row.append(activation);
      row.append(el("td", p.is_version_vulnerable === true ? "plugin-flag" : "plugin-vulnerability",
        p.is_version_vulnerable === true ? "⚠ Flagged" : p.is_version_vulnerable === false ? "No flag" : "Not assessed"));
      body.append(row);
    }
    table.append(body); section.append(table);
    section.append(el("p", "observation-time", "Flagged means the provider reports a vulnerability in the installed version. Not assessed means no matching provider result."));
  }
  return section;
}

function row(w) {
  const li = el("li", "website-card");
  li.dataset.websiteId = w.id;
  li.id = `website-${w.id}`;
  const b = el("button", "row");
  b.type = "button";
  const open = ui.picked === w.id;
  b.setAttribute("aria-expanded", String(open));
  b.setAttribute("aria-controls", `details-${w.id}`);
  b.append(el("span", `tag ${w.state}`));
  b.lastChild.setAttribute("aria-label", WORD[w.state]);
  const who = el("span", "who");
  who.append(el("span", "name", w.matchingWebsites ? w.hostname || w.name : w.name));
  const hosting = el("span", "hosting-meta");
  hosting.append(PulseTech.badge(hostingName(w)));
  if (w.network) hosting.append(PulseTech.badge(w.network));
  who.append(hosting);
  who.append(el("span", "website-kind", websiteKind(w)));
  const side = el("span", "side");
  const f = websiteFacts(w);
  const versions = [
    f.php_version && `PHP ${f.php_version}`,
    f.wordpress_version && `WP ${f.wordpress_version}`,
  ]
    .filter(Boolean)
    .join(" · ");
  if (versions) {
    const tags = el("span", "tech-tags");
    if (f.php_version) tags.append(PulseTech.badge(`PHP ${f.php_version}`, "PHP", "binary"));
    if (f.wordpress_version) tags.append(PulseTech.badge(`WordPress ${f.wordpress_version}`, "WordPress", "binary"));
    side.append(tags);
  }
  if (w.facts?.http_status) side.append(el("span", null, `HTTP ${w.facts.http_status}`));
  if (w.hosting && versions) side.append(el("span", null, `Shared ${w.hosting.name} hosting`));
  if (w.facts?.visits_24h != null)
    side.append(el("span", null, `${w.facts.visits_24h.toLocaleString()} visits · 24 h`));
  side.append(el("span", "when", w.lastCheck ? ago(w.lastCheck) :
    w.network ? "No individual check received" : "No checks received"));
  b.append(who, side);
  const children = subsites(w);
  if (children.length) b.append(el("span", "alert installation-scope", `${children.length} subsite${children.length === 1 ? "" : "s"} · Patch shared files at this installation`));
  if (w.matchingWebsites) b.append(el("span", "alert installation-scope", `${w.matchingWebsites.length} matching website${w.matchingWebsites.length === 1 ? "" : "s"} · Status shown is the installation’s own check`));
  if (w.hosting) b.append(el("span", "alert installation-scope", `Patch parent: ${w.hosting.hostname || w.hosting.name}`));
  const plugins = cardPlugins(w);
  if (plugins.length) b.append(el("span", "alert plugin-location", `WordPress plugins · ${pluginLocation(w)}`));
  const flagged = plugins.filter(p => p.flagged.size);
  for (const {plugin, environments, flagged: flags} of plugins) {
    const warning = el("span", `alert plugin-warning ${flags.size ? "warning" : ""}`);
    warning.append(el("span", "plugin-warning-name", `${plugin.title || plugin.slug} · ${plugin.version || "Version unknown"}`));
    warning.append(el("span", "plugin-warning-scope", `${flags.size ? "⚠ Provider flagged" : "Installed"} · ${w.hosting || w.network ? "Shared installation · " : ""}${[...(flags.size ? flags : environments)].join(" / ")}`));
    b.append(warning);
  }
  const liveFlagged = new Set((websitePlugins(w)?.environments || []).filter(env => env.is_live)
    .flatMap(env => (env.plugins || []).filter(p => p.is_version_vulnerable === true).map(p => p.slug))).size;
  if (flagged.length && Number(f.plugins_vulnerable) > liveFlagged)
    b.append(el("span", "alert warning", "Additional plugins or themes flagged; details unavailable"));
  for (const a of (w.alerts || []).filter(a => !flagged.length || !genericPluginAlert(a)).slice(0, 2))
    b.append(el("span", `alert ${a.severity}`, a.text));
  b.addEventListener("click", () => pick(ui.picked === w.id ? null : w.id));
  li.append(b);
  const actions = el("div", "card-actions");
  if (w.url) {
    const visit = el("a", "card-action");
    visit.href = w.url;
    visit.target = "_blank";
    visit.rel = "noopener noreferrer";
    visit.title = "Open the site in a new tab";
    visit.setAttribute("aria-label", `Open ${w.name} in a new tab`);
    visit.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3h7v7M10 14 21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></svg>';
    actions.append(visit);
  }
  actions.append(Pulse.copyLink(() => {
    const url = websiteUrl();
    url.searchParams.set("site", w.id);
    return url.href;
  }, w.name));
  li.append(actions);
  if (open) li.append(renderDetails(w));
  return li;
}

function renderGroups(anchor = null) {
  const wrap = document.getElementById("groups");
  const position = typeof window !== "undefined" ? {x: window.scrollX, y: window.scrollY, anchor} : null;
  const members = visibleWebsites();
  if (wrap.style && wrap.getBoundingClientRect) wrap.style.minHeight = `${wrap.getBoundingClientRect().height}px`;
  const previous = new Map([...wrap.children].map(card => [card.dataset.websiteId, card]));
  const cards = members.map(w => {
    const next = row(w);
    const card = previous.get(w.id);
    if (!card) return next;
    // Preserve the focused disclosure and its scroll anchor across expansion and polling.
    const button = card.firstElementChild;
    button.replaceChildren(...next.firstElementChild.childNodes);
    button.setAttribute("aria-expanded", next.firstElementChild.getAttribute("aria-expanded"));
    while (card.children.length > 1) card.lastChild.remove();
    card.append(...[...next.children].slice(1));
    return card;
  });
  if (!cards.length) cards.push(el("li", "empty-state", searchExpression().error || "No websites match these filters."));
  const retained = new Set(cards);
  for (const card of [...wrap.children]) if (!retained.has(card)) card.remove();
  cards.forEach((card, index) => {
    if (wrap.children[index] !== card) wrap.insertBefore(card, wrap.children[index] || null);
  });
  renderTotal(members);
  scheduleLayout(position);
}

function pick(id) {
  const card = document.getElementById(`website-${id || ui.picked}`);
  const anchor = card ? {id: card.id, top: card.getBoundingClientRect().top} : null;
  ui.picked = id;
  writeFilters();
  renderGroups(anchor);
}

function renderTotal(members = visibleWebsites()) {
  const total = document.getElementById("total");
  if (installationView()) {
    const targets = members.filter(w => w.matchingWebsites);
    const matched = data.websites.filter(matches).length;
    total.replaceChildren(el("b", null, `${targets.length} patching target${targets.length === 1 ? "" : "s"}`),
      document.createTextNode(` · ${matched} matching website${matched === 1 ? "" : "s"}`));
    return;
  }
  const count = members.length === data.websites.length
    ? `${data.websites.length} websites`
    : `${members.length} of ${data.websites.length} websites`;
  const up = members.filter((w) => w.state === "up").length;
  const unknown = members.filter((w) => w.state === "unknown").length;
  total.replaceChildren(el("b", null, count), document.createTextNode(` · ${up} up`));
  if (unknown) total.append(document.createTextNode(` · ${unknown} not reporting`));
}

function render() {
  if (!data) return;
  for (const b of document.querySelectorAll("#filter button"))
    b.setAttribute("aria-pressed", String(b.dataset.v === ui.filter));
  document.getElementById("sample").hidden = !data.sample;
  if (document.activeElement !== document.getElementById("search")) document.getElementById("search").value = ui.query;
  document.getElementById("clear-filters").hidden = !hasFilters();
  const error = searchExpression().error;
  document.getElementById("search").setAttribute("aria-invalid", String(Boolean(error)));
  document.getElementById("search-help").textContent = error || 'Use AND, OR, NOT, parentheses or "quoted phrases". Spaces mean AND.';
  document.getElementById("view").value = ui.view;
  renderDropdowns();
  renderPicture();
  renderGroups();
  if (installationView() && !error) document.getElementById("search-help").textContent += " Showing installation patching targets; expand for subsites and environment details.";
  for (const id of ["hosting", "network", "view"]) PulseTech.picker(document.getElementById(id));
}

document.getElementById("filter").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  ui.filter = ui.filter === b.dataset.v ? "all" : b.dataset.v;
  writeFilters();
  render();
});
document.getElementById("search").addEventListener("input", (e) => {
  ui.query = e.target.value.trim().slice(0, 500);
  writeFilters(true);
  render();
});
for (const event of ["popstate", "hashchange"]) window.addEventListener(event, () => { readFilters(); if (data) render(); });
for (const [id, field] of [["hosting", "place"], ["network", "network"]])
  document.getElementById(id).addEventListener("change", e => { ui[field] = e.target.value || null; writeFilters(); render(); });
document.getElementById("view").addEventListener("change", e => { ui.view = e.target.value; writeFilters(); render(); });
document.getElementById("clear-filters").addEventListener("click", () => { clearFilters(); writeFilters(); render(); });
document.getElementById("filter-link").append(Pulse.copyLink(() => websiteUrl().href, "filtered websites"));
new ResizeObserver(scheduleLayout).observe(document.getElementById("groups"));
document.fonts.ready.then(scheduleLayout);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && ui.picked) pick(null);
  if (
    e.key === "/" &&
    !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName)
  ) {
    e.preventDefault();
    document.getElementById("search").focus();
  }
});

(async () => {
  await Pulse.shell({
    current: "websites",
    title: "Websites Status",
    context: "Websites, where they are hosted and how they answer",
    hideOverview: true,
  });
  Pulse.poll(async () => {
    const r = await fetch("api/status", { cache: "no-store" });
    if (!r.ok) throw new Error(`status ${r.status}`);
    data = await r.json();
    render();
    document.getElementById("updated").textContent =
      `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
  }, 30000);
})();

window.addEventListener("technology-brands-ready", () => { if (data) render(); });
