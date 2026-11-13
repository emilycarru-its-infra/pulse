from copy import deepcopy
from datetime import datetime, timedelta, timezone

from pulse_servers.application_assessments import assessments
from pulse_servers.runtimes import view
from pulse_servers.service import ServersService

NOW = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
CVE = "CVE-2026-12345"


def inventory(state="verified_fixed"):
    return {"freshness": "fresh", "observed_at": NOW.isoformat(), "advisories": [{
        "cve": CVE, "component": "OpenSSH", "scope": "host", "state": state, "reason": "Reviewed application evidence",
        "advisory_observed_at": NOW.isoformat(), "assessment_scope": "application_configuration",
    }]}


def test_application_assessment_is_independent_of_kernel_and_uptime():
    value = inventory("needs_patch")
    result = assessments(value, [CVE], NOW)[0]
    assert result["state"] == "needs_patch" and result["category"] == "application"
    assert result["scope"] == "host"
    assert "kernel" not in result
    value["freshness"] = "stale"
    result = assessments(value, [CVE], NOW)[0]
    assert result["state"] == "unknown" and result["last_known_state"] == "needs_patch"


def test_stale_vendor_reference_and_unknown_coverage_never_become_fixed():
    assert assessments({}, [CVE], NOW)[0]["state"] == "unknown"
    value = inventory()
    value["advisories"][0]["advisory_observed_at"] = (NOW - timedelta(hours=2)).isoformat()
    assert assessments(value, [CVE], NOW)[0]["state"] == "unknown"


def test_multiple_components_cannot_hide_an_affected_package():
    value = inventory()
    value["advisories"].append({**value["advisories"][0], "state": "needs_patch", "component": "Another installation"})
    assert assessments(value, [CVE], NOW)[0]["state"] == "needs_patch"


def test_browser_view_excludes_sensitive_configuration_predicates():
    facts = {"advisories": inventory()["advisories"], "components": [],
             "openssh": {"instances": [{"eligible_star_account_present": True}]}}
    original = deepcopy(facts)
    stored = {"attempt": {"received_at": NOW.isoformat(), "outcome": "accepted", "facts": {}},
              "success": {"facts": facts, "observed_at": NOW.isoformat(), "item_id": "asset", "observation_id": "receipt"}}
    assert "openssh" not in view(stored, NOW)
    assert facts == original


def test_configured_and_discovered_application_cves_get_unknown_rows_for_missing_hosts(monkeypatch):
    monkeypatch.setenv("PULSE_APPLICATION_CVES", CVE)
    class Store:
        def rows(self):
            return {}
    service = ServersService({"servers": [{"id": "one"}]}, lambda *a: {"state": "up"}, runtime_store=Store())
    status = service.status(NOW)
    assert status["patching"]["application_cves"] == [CVE]
    assert status["servers"][0]["patches"][0]["state"] == "unknown"


def test_publication_time_and_severity_pass_through_only_when_well_formed():
    value = inventory("needs_patch")
    value["advisories"][0].update(published_at="2026-01-03T00:00:00+00:00", severity="critical")
    result = assessments(value, [CVE], NOW)[0]
    assert (result["published_at"], result["severity"]) == ("2026-01-03T00:00:00+00:00", "critical")
    value["advisories"][0].update(published_at="yesterday", severity="<b>bad</b>")
    result = assessments(value, [CVE], NOW)[0]
    assert (result["published_at"], result["severity"]) == (None, None)
    value["advisories"][0].update(published_at="2026-01-03T00:00:00", severity=None)
    assert assessments(value, [CVE], NOW)[0]["published_at"] is None
