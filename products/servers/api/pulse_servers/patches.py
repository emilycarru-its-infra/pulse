"""Read-only, freshness-aware views of canonical kernel/vendor assessment evidence."""

import re
from datetime import timedelta

from pulse_servers.runtimes import time

STATES = {
    "needs_patch",
    "restart_required",
    "awaiting_vendor_fix",
    "verified_fixed",
    "not_affected",
    "unknown",
}


def assessments(server, inventory, cves, now):
    kernel = inventory.get("kernel") or {}
    evidence = kernel.get("assessments") or []
    linux = bool(kernel) or bool(
        re.search(
            r"linux|ubuntu|debian|rocky|centos|alma|red hat|suse",
            server.get("os") or "",
            re.IGNORECASE,
        )
    )
    non_linux = not linux and bool(
        re.search(
            r"windows|macos|darwin|freebsd", server.get("os") or "", re.IGNORECASE
        )
    )
    results = []
    for cve in cves:
        result = {
            "cve": cve,
            "state": "unknown",
            "reason": "No kernel assessment received",
            "applicable": not non_linux,
            "kernel": kernel.get("running_release"),
            "observed_at": inventory.get("observed_at"),
            "distribution": kernel.get("distribution", {}),
            "running_package": kernel.get("running_package"),
            "reboot_required": kernel.get("reboot_required"),
            "livepatch": kernel.get("livepatch"),
            "tcp4_listener_count": kernel.get("tcp4_listener_count"),
            "mptcp_listener_count": kernel.get("mptcp_listener_count"),
            "exposure": kernel.get("exposure", "unassessed"),
            "gaps": kernel.get("gaps", []),
        }
        if non_linux:
            result.update(
                state="not_affected",
                reason="Recorded platform is outside this Linux kernel advisory's scope",
            )
        else:
            match = next(
                (r for r in evidence if isinstance(r, dict) and r.get("cve") == cve),
                None,
            )
            if match:
                for key in (
                    "vendor",
                    "vendor_state",
                    "fixed_version",
                    "source_package",
                    "release",
                    "source_updated_at",
                    "advisory_observed_at",
                ):
                    result[key] = match.get(key)
                state = match.get("state")
                result.update(
                    state=state if state in STATES else "unknown",
                    reason=str(match.get("reason") or "Assessment incomplete")[:500],
                )
                try:
                    checked = time(match["advisory_observed_at"])
                    current_vendor = (
                        timedelta(minutes=-2) <= now - checked <= timedelta(hours=1)
                    )
                except (KeyError, TypeError, ValueError):
                    current_vendor = False
                if inventory.get("freshness") != "fresh" or (
                    result["state"] != "unknown" and not current_vendor
                ):
                    result.update(
                        last_known_state=result["state"],
                        state="unknown",
                        reason="Kernel or vendor evidence is stale or unavailable",
                    )
        results.append(result)
    return results
