import json
from datetime import UTC, datetime
from pathlib import Path

from pulse_websites.service import WebsitesService
from pulse_websites.simulate import health

EXAMPLE = json.loads((Path(__file__).resolve().parents[2] / "examples" / "catalog.json").read_text())
NOW = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)


def test_status_groups_every_website_and_hides_matching_keys():
    status = WebsitesService({**EXAMPLE, "sample": True}, health).status(NOW)
    assert status["sample"] is True
    assert len(status["websites"]) == len(EXAMPLE["websites"])
    assert sum(g["websites"] for g in status["groups"]) == len(EXAMPLE["websites"])
    assert all("kinsta_site_id" not in w and "site24x7_monitor_id" not in w for w in status["websites"])


def test_summary_counts():
    summary = WebsitesService(EXAMPLE, health).summary(NOW)
    assert summary["product"] == "websites"
    assert sum(summary["counts"].values()) == summary["websites"] == len(EXAMPLE["websites"])


def test_empty_catalog_is_idle():
    assert WebsitesService({"websites": []}, health).summary(NOW)["level"] == "idle"


def test_simulation_is_stable():
    w = EXAMPLE["websites"][0]
    assert health(w, {}, NOW) == health(w, {}, NOW)
