from datetime import UTC, datetime, timedelta
from pulse_servers.patches import assessments

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def inventory(state="verified_fixed", age=0, vendor_age=0):
    return {
        "freshness": "fresh" if age == 0 else "stale",
        "observed_at": (NOW - timedelta(hours=age)).isoformat(),
        "kernel": {
            "running_release": "6.8.0-example",
            "assessments": [
                {
                    "cve": "CVE-2026-12345",
                    "state": state,
                    "reason": "Vendor package evidence",
                    "advisory_observed_at": (
                        NOW - timedelta(hours=vendor_age)
                    ).isoformat(),
                }
            ],
        },
    }


def test_fresh_and_stale_kernel_and_vendor_evidence_are_distinct():
    for host_age, vendor_age in [(0, 0), (2, 0), (0, 2)]:
        row = assessments(
            {"os": "Ubuntu 24.04"},
            inventory(age=host_age, vendor_age=vendor_age),
            ["CVE-2026-12345"],
            NOW,
        )[0]
        assert row["state"] == (
            "unknown" if host_age or vendor_age else "verified_fixed"
        )


def test_missing_kernel_never_becomes_compliant_from_healthy_server():
    row = assessments(
        {"os": "Ubuntu 24.04", "state": "up"}, {}, ["CVE-2026-12345"], NOW
    )[0]
    assert row["state"] == "unknown" and row["applicable"]


def test_non_linux_scope_and_unknown_platform_are_separate():
    assert not assessments({"os": "Windows Server 2025"}, {}, ["CVE-2026-12345"], NOW)[
        0
    ]["applicable"]
    row = assessments({"os": "Custom OS"}, {}, ["CVE-2026-12345"], NOW)[0]
    assert row["applicable"] and row["state"] == "unknown"


def test_unknown_assessment_state_fails_closed():
    assert (
        assessments({"os": "Ubuntu"}, inventory("looks_safe"), ["CVE-2026-12345"], NOW)[
            0
        ]["state"]
        == "unknown"
    )
