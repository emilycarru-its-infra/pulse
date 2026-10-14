from pathlib import Path

import yaml

from pulse_software.managed import build_suite, identity, manifest_packages


def source(root, manifest, packages):
    (root / "manifests").mkdir(parents=True)
    (root / "pkgsinfo").mkdir()
    (root / "icons").mkdir()
    (root / "manifests/ManagedApps.yaml").write_text(yaml.safe_dump(manifest))
    for i, package in enumerate(packages):
        (root / f"pkgsinfo/{i}.yaml").write_text(yaml.safe_dump(package))
    return root


def test_manifest_membership_is_required_and_hidden_packages_cannot_be_discovered(tmp_path):
    root = source(tmp_path / "mac", {"managed_installs": ["Sketch", "BackgroundAgent", "Unpublished"]}, [
        {"name": "Sketch", "display_name": "Sketch", "catalogs": ["Production"], "category": "Design",
         "installs": [{"CFBundleName": "Sketch Studio", "path": "/Applications/Sketch Studio 2026.app"}]},
        {"name": "BackgroundAgent", "catalogs": ["Production"]},
        {"name": "Unrelated", "catalogs": ["Production"]},
        {"name": "Unpublished", "catalogs": ["Testing"]}])
    result = build_suite({"mac": root}, {"hidden_packages": ["BackgroundAgent"]}, tmp_path / "icons")
    assert [p["name"] for p in result["products"]] == ["Sketch"]
    assert "sketchstudio" in result["products"][0]["aliases"]
    assert result["unresolved"] == [{"platform": "mac", "package": "Unpublished", "reason": "no production package metadata"}]


def test_bundle_expansion_merges_platforms_and_does_not_match_bundle_helpers(tmp_path):
    mac = source(tmp_path / "mac", {"managed_installs": ["Sketch"]}, [{"name": "Sketch", "catalogs": ["Production"]}])
    win = source(tmp_path / "win", {"conditional_items": [{"condition": "supported", "managed_installs": ["DesignBundle"]}]}, [{"name": "DesignBundle", "catalogs": ["Production"]}])
    policy = {"products": [{"name": "Sketch", "packages": ["Sketch", "DesignBundle"], "aliases": ["Sketch Studio"]},
                           {"name": "Sculpt", "packages": ["DesignBundle"], "aliases": ["Sculpt Studio"]}]}
    result = build_suite({"mac": mac, "windows": win}, policy, tmp_path / "icons")
    sketch = next(p for p in result["products"] if p["name"] == "Sketch")
    assert sketch["platforms"] == ["mac", "windows"]
    assert "designbundle" not in sketch["aliases"] and "sketchstudio" in sketch["aliases"]


def test_manifest_uninstalls_are_not_eligible_and_version_names_normalize():
    assert manifest_packages({"managed_apps": ["Sketch"], "optional_installs": ["Retired"], "managed_uninstalls": ["Retired"]}) == {"Sketch"}
    assert identity("Sketch Studio 2026 (64-bit)") == identity("Sketch Studio")
    assert identity("Sketch Studio 2026.app") == identity("Sketch Studio")
    assert identity("Sketch Studio 17.0v7") == identity("Sketch Studio")
    assert identity("Sketch9.0v3") == identity("Sketch")
    assert identity("Sketch 2026 SP03.2") == identity("Sketch")
    assert identity("Sketch (x64) 5.3.4 (git bd6e8d0)") == identity("Sketch")
    assert identity("Sketch Engine") != identity("Sketch")
    assert identity("Sketch Studio") != identity("Sketch")
