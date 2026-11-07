"""A minimized view of accepted application assessments; no host scanning or CVE inference."""

from datetime import timedelta

from pulse_servers.runtimes import time

STATES = {"unknown", "candidate", "needs_patch", "restart_required", "verified_fixed", "not_affected"}
PRIORITY = {"needs_patch": 0, "restart_required": 1, "candidate": 2, "unknown": 3, "verified_fixed": 4, "not_affected": 5}


def assessments(inventory, cves, now):
    results = []
    for cve in cves:
        entries = [v for v in inventory.get("advisories", []) if v.get("cve") == cve]
        if not entries:
            results.append({"cve": cve, "category": "application", "applicable": True,
                            "state": "unknown", "reason": "No application advisory assessment received"})
            continue
        candidates = []
        for entry in entries:
            state = entry.get("state") if entry.get("state") in STATES else "unknown"
            result = {k: entry.get(k) for k in (
                "cve", "component", "vendor", "fixed_version", "package_name", "package_version",
                "assessment_scope", "source_updated_at", "advisory_observed_at", "advisory_id", "advisory_url",
            )}
            result.update(category="application", applicable=True, state=state,
                          reason=str(entry.get("reason") or "Assessment incomplete")[:1000],
                          observed_at=inventory.get("observed_at"))
            try:
                age = now - time(entry.get("advisory_observed_at"))
                current_vendor = timedelta(minutes=-2) <= age <= timedelta(hours=1)
            except (TypeError, ValueError):
                current_vendor = False
            if inventory.get("freshness") != "fresh" or not current_vendor:
                result.update(last_known_state=state, state="unknown", reason="Application or vendor evidence is stale or unavailable")
            candidates.append(result)
        results.append(min(candidates, key=lambda r: PRIORITY[r["state"]]))
    return results
