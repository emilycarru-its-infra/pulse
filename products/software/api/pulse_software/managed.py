"""Compile a discoverable software suite from managed manifests and package metadata."""
import hashlib
import json
import re
import shutil
from pathlib import Path

import yaml

from .inventory import app_id


def identity(name):
    text = re.sub(r"\.app$", "", name.casefold())
    text = re.sub(r"\(\s*git\s+[0-9a-f]+\s*\)", "", text)
    text = re.sub(r"\bsp\d+(?:\.\d+)*\b", "", text)
    text = re.sub(r"(?<=[a-z])\d+(?:\.\d+)+(?:v\d+)?\b", "", text)
    text = re.sub(r"\b(?:x64|x86|arm64|64-bit|32-bit)\b", "", text)
    text = re.sub(r"\bv?\d+(?:\.\d+)+(?:v\d+)?\b", "", text)
    text = re.sub(r"\b\d+(?:\.\d+)*\b", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def manifest_packages(manifest):
    names = set()
    for field in ("managed_installs", "managed_apps", "managed_updates", "optional_installs"):
        names.update(x for x in manifest.get(field) or [] if isinstance(x, str))
    for child in manifest.get("conditional_items") or []:
        names.update(manifest_packages(child))
    return names - set(manifest.get("managed_uninstalls") or [])


def build_suite(sources, policy, icon_output):
    """Sources are platform -> deployment directory. Policy owns editorial exclusions and suite expansions."""
    icon_output = Path(icon_output)
    icon_output.mkdir(parents=True, exist_ok=True)
    hidden = {identity(n) for n in policy.get("hidden_packages", [])}
    overrides = policy.get("products", [])
    entries, reports = {}, []
    for platform, source in sources.items():
        root = Path(source)
        manifest = yaml.safe_load((root / "manifests/ManagedApps.yaml").read_text())
        wanted = manifest_packages(manifest)
        packages = {}
        for file in sorted((root / "pkgsinfo").rglob("*.yaml")):
            data = yaml.safe_load(file.read_text())
            if isinstance(data, dict) and "Production" in (data.get("catalogs") or []):
                packages.setdefault(str(data.get("name") or "").casefold(), []).append(data)
        for name in sorted(wanted):
            if identity(name) in hidden:
                continue
            metadata = [m for alias in [name, *policy.get("package_aliases", {}).get(name, [])] for m in packages.get(alias.casefold(), [])]
            if not metadata:
                reports.append({"platform": platform, "package": name, "reason": "no production package metadata"})
                continue
            explicit = [p for p in overrides if name in p.get("packages", [])]
            definitions = explicit or [{"name": metadata[-1].get("display_name") or name}]
            for definition in definitions:
                title = definition["name"]
                key = identity(title)
                entry = entries.setdefault(key, {"id": app_id(title), "name": title, "aliases": set(),
                    "platforms": set(), "packages": set(), "iconNames": set(), "category": definition.get("category") or metadata[-1].get("category") or "Applications", "icon": None})
                entry["platforms"].add(platform)
                entry["packages"].add(name)
                aliases = [title, *definition.get("aliases", [])]
                if not explicit:
                    aliases.append(name)
                    for data in metadata:
                        aliases.append(data.get("display_name") or name)
                        for install in data.get("installs") or []:
                            if install.get("CFBundleName"):
                                aliases.append(install["CFBundleName"])
                            path = str(install.get("path") or "")
                            if path.endswith(".app"):
                                aliases.append(Path(path).stem)
                entry["aliases"].update(identity(a) for a in aliases if a)
                candidates = [definition.get("icon"), *[m.get("icon_name") for m in reversed(metadata)], name + ".png", title + ".png"]
                entry["iconNames"].update(c for c in candidates if c)
                for candidate in candidates:
                    if not candidate:
                        continue
                    icon = root / "icons" / candidate
                    if icon.parent.resolve() != (root / "icons").resolve() or not icon.is_file() or icon.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                        continue
                    digest = hashlib.sha256(icon.read_bytes()).hexdigest() + icon.suffix.lower()
                    shutil.copyfile(icon, icon_output / digest)
                    if not entry["icon"]:
                        entry["icon"] = "software-icons/" + digest
                    break
    for entry in entries.values():
        if entry["icon"]:
            continue
        for source in sources.values():
            icons = Path(source) / "icons"
            for candidate in sorted(entry["iconNames"]):
                icon = icons / candidate
                if icon.parent.resolve() == icons.resolve() and icon.is_file() and icon.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    digest = hashlib.sha256(icon.read_bytes()).hexdigest() + icon.suffix.lower()
                    shutil.copyfile(icon, icon_output / digest)
                    entry["icon"] = "software-icons/" + digest
                    break
            if entry["icon"]:
                break
    products = [{**{k: v for k, v in e.items() if k != "iconNames"}, "aliases": sorted(e["aliases"]), "platforms": sorted(e["platforms"]), "packages": sorted(e["packages"])}
                for e in sorted(entries.values(), key=lambda e: e["name"].casefold())]
    return {"products": products, "unresolved": reports}
