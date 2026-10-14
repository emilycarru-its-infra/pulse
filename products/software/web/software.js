Pulse.computersOptions = { current: "software", defaultMode: "list", title: "Find Software", context: "Find the software you need on a free campus computer" };
const softwareInput = document.getElementById("software");
const versionInput = document.getElementById("software-version");
const softwareNote = document.getElementById("software-note");
let softwareIndex = [], softwareGeneration = 0;
let softwareIcons = {};
const iconKey = (name) => name.toLowerCase().replace(/\b(20\d{2}|\d+(?:\.\d+)+)\b/g, "").replace(/[^a-z0-9]/g, "");
fetch("software-icons/index.json").then((r) => r.ok ? r.json() : {}).then((icons) => { softwareIcons = icons; renderSoftwareSuggestions(); }).catch(() => {});
function renderSoftwareSuggestions() {
  const query = softwareInput.value.trim().toLowerCase();
  const choices = softwareIndex.filter((a) => a.name.toLowerCase().includes(query)).sort((a, b) =>
    Number(!!softwareIcons[iconKey(b.name)]) - Number(!!softwareIcons[iconKey(a.name)]) || b.computers - a.computers || a.name.localeCompare(b.name)).slice(0, 12);
  document.getElementById("software-suggestions").replaceChildren(...choices.map((a) => {
    const b = document.createElement("button"); b.type = "button";
    b.setAttribute("aria-pressed", String(a.name.toLowerCase() === query));
    const icon = softwareIcons[iconKey(a.name)];
    if (icon && /^software-icons\/[a-f0-9]+\.(png|jpg|jpeg|svg|webp)$/i.test(icon)) {
      const img = document.createElement("img"); img.src = icon; img.alt = ""; img.width = 32; img.height = 32;
      img.addEventListener("error", () => img.remove(), { once: true }); b.append(img);
    } else {
      const fallback = document.createElement("span"); fallback.className = "software-icon-fallback";
      fallback.setAttribute("aria-hidden", "true"); fallback.textContent = a.name.slice(0, 1).toUpperCase(); b.append(fallback);
    }
    const text = document.createElement("span"); text.textContent = a.name;
    const count = document.createElement("small"); count.textContent = `${a.computers} computer${a.computers === 1 ? "" : "s"} reporting recently`;
    text.append(count); b.append(text);
    b.addEventListener("click", () => { softwareInput.value = a.name; softwareInput.dispatchEvent(new Event("input")); });
    return b;
  }));
}
const originalTitle = "Choose software to find computers where it was recently reported installed.";
Pulse.loadComputerStatus = async function () {
  const generation = softwareGeneration;
  const selected = softwareIndex.find((a) => a.name.toLowerCase() === softwareInput.value.trim().toLowerCase());
  const params = new URLSearchParams();
  if (selected) params.set("software", selected.id);
  if (selected && versionInput.value) params.set("version", versionInput.value);
  try {
    const r = await fetch(`api/status?${params}`);
    if (!r.ok) throw new Error("Software availability is temporarily unavailable. Please try again shortly.");
    const data = await r.json();
    if (generation !== softwareGeneration) return Pulse.loadComputerStatus();
    softwareIndex = data.software;
    renderSoftwareSuggestions();
    const options = document.getElementById("software-options");
    options.replaceChildren(...softwareIndex.map((a) => {
      const option = document.createElement("option"); option.value = a.name; return option;
    }));
    if (softwareInput.value.trim() && !selected) {
      for (const space of data.spaces) for (const seat of space.seats) seat.softwareMatch = false;
      softwareNote.textContent = "Choose a software title from the suggestions. No matching title? Its installation may not have been reported yet.";
    } else if (selected) {
      softwareNote.textContent = `Showing ${selected.name}${versionInput.value ? ` ${versionInput.value}` : ""}. Installation reports must be less than ${data.inventoryMaxAgeHours} hours old. Free means likely unattended; licence availability is not yet checked.`;
    } else {
      softwareNote.textContent = `${originalTitle} ${data.inventoryComputers} of ${data.catalogComputers} computers have recent software reports. Free means likely unattended.`;
    }
    document.querySelector(".stage").hidden = false;
    return data;
  } catch (e) {
    softwareNote.textContent = e.message;
    document.querySelector(".stage").hidden = true;
    document.getElementById("total").textContent = "Availability unavailable";
    throw e;
  }
};
let softwareDebounce;
function softwareChanged() {
  softwareGeneration++;
  clearTimeout(softwareDebounce);
  softwareDebounce = setTimeout(async () => {
    try {
      state.status = await Pulse.loadComputerStatus(); state.drawn = null; render();
    } catch (e) { console.error(e); }
  }, 250);
}
softwareInput.addEventListener("input", () => {
  renderSoftwareSuggestions();
  const selected = softwareIndex.find((a) => a.name.toLowerCase() === softwareInput.value.trim().toLowerCase());
  versionInput.replaceChildren(new Option("Any version", ""), ...(selected?.versions || []).map((v) => new Option(v, v)));
  softwareChanged();
});
versionInput.addEventListener("change", softwareChanged);
document.getElementById("clear-software").addEventListener("click", () => {
  softwareInput.value = ""; versionInput.replaceChildren(new Option("Any version", "")); softwareChanged(); softwareInput.focus();
});
