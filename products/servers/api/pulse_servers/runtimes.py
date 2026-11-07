"""Read-only projection of canonical active-runtime observations, independent of health."""

import json
import re
import threading
from datetime import datetime, timedelta
from uuid import UUID

CONTRACT = "pulse.server-runtimes/1"
MAX_AGE = timedelta(hours=1)


class ContractError(ValueError):
    pass


def time(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (ValueError, AttributeError, TypeError):
        raise ContractError("observation timestamps must include a timezone") from None


def parse(body, now):
    if not isinstance(body, dict) or body.get("contract") != CONTRACT:
        raise ContractError("unsupported runtime projection contract")
    rows = body.get("servers")
    if not isinstance(rows, list) or len(rows) > 500:
        raise ContractError("servers must be a bounded list")
    seen = set()
    for row in rows:
        try:
            for key in ("item_id", "reference_id", "observation_id"):
                UUID(row[key])
            hybrid = set(row["key"]) == {"aws_ssm_node_id"}
            if set(row["key"]) not in ({"aws_instance_id"}, {"aws_ssm_node_id"}):
                raise ValueError()
            iid = row["key"]["aws_ssm_node_id" if hybrid else "aws_instance_id"]
            if (
                not isinstance(iid, str)
                or not iid.startswith("mi-" if hybrid else "i-")
                or len(iid) > 25
                or iid in seen
            ):
                raise ValueError()
            if hybrid and not re.fullmatch(r"mi-[0-9a-f]{17}", iid):
                raise ValueError()
            seen.add(iid)
            if row["outcome"] not in {"accepted", "collection_failed"}:
                raise ValueError()
            if time(row["received_at"]) > now + timedelta(minutes=2):
                raise ValueError()
            facts = row["facts"]
            if (
                facts["contract"] != "server-live-runtimes/1"
                or facts["instance_id"] != iid
            ):
                raise ValueError()
            kernel = facts.get("kernel")
            advisories = facts.get("advisories", [])
            if not isinstance(advisories, list) or len(advisories) > 16:
                raise ValueError()
            for advisory in advisories:
                if not isinstance(advisory, dict) or advisory.get("state") not in {
                    "unknown", "candidate", "needs_patch", "restart_required", "verified_fixed", "not_affected"
                } or not isinstance(advisory.get("cve"), str):
                    raise ValueError()
            if kernel is not None:
                if (not isinstance(kernel, dict) or kernel.get("contract") != "linux-kernel-evidence/1"
                        or not isinstance(kernel.get("running_release"), str)
                        or len(kernel.get("assessments", [])) > 16
                        or len(json.dumps(kernel)) > 20000):
                    raise ValueError()
                for assessment in kernel.get("assessments", []):
                    if not isinstance(assessment, dict) or not isinstance(assessment.get("cve"), str):
                        raise ValueError()
            components = facts["components"]
            if not isinstance(components, list) or len(components) > 64:
                raise ValueError()
            if row["outcome"] == "accepted":
                if facts["collection_state"] not in {"observed", "partial"} or time(
                    row["observed_at"]
                ) > now + timedelta(minutes=2):
                    raise ValueError()
            elif components or row["observed_at"] is not None:
                raise ValueError()
            for component in components:
                if (
                    not isinstance(component, dict)
                    or type(component.get("running")) is not bool
                ):
                    raise ValueError()
                installed_kind = component.get("evidence_kind") in {
                    "installed_executable_self_report", "installed_executable_unverified", "installed_binary_file_metadata"
                }
                if installed_kind != (component["running"] is False):
                    raise ValueError()
                if installed_kind and (component.get("scope") != "host" or component.get("pids") != []
                                       or component.get("process_count") != 0 or not component.get("executable")):
                    raise ValueError()
                if component.get("scope") not in {"host", "container", "isolated"}:
                    raise ValueError()
                if (
                    not isinstance(component.get("name"), str)
                    or len(component["name"]) > 100
                ):
                    raise ValueError()
                if component.get("version") is not None and not isinstance(
                    component["version"], str
                ):
                    raise ValueError()
            if len(json.dumps(row).encode()) > 32768:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ContractError("invalid canonical runtime observation") from None
    return rows


def combined(old, incoming):
    """Preserve last good evidence after a failed attempt; ignore duplicate/late deliveries."""
    old = old or {}
    attempt = old.get("attempt")
    if attempt and time(attempt["received_at"]) >= time(incoming["received_at"]):
        return old
    result = {
        **old,
        "attempt": {
            k: incoming[k] for k in ("received_at", "outcome", "observation_id")
        },
    }
    result["attempt"]["facts"] = {"reason": incoming["facts"].get("reason")}
    if incoming["outcome"] == "accepted":
        success = old.get("success")
        if not success or time(incoming["observed_at"]) >= time(success["observed_at"]):
            result["success"] = incoming
    return result


class Store:
    def __init__(self, table=None):
        self.table = table
        self.memory = {}
        self.lock = threading.Lock()

    def put(self, sid, incoming):
        if self.table is None:
            with self.lock:
                self.memory[sid] = combined(self.memory.get(sid), incoming)
            return
        from azure.core import MatchConditions
        from azure.core.exceptions import (
            ResourceExistsError,
            ResourceModifiedError,
            ResourceNotFoundError,
        )

        for _ in range(5):
            try:
                entity = self.table.get_entity("runtime", sid)
            except ResourceNotFoundError:
                entity = None
            old = json.loads(entity["value"]) if entity else {}
            result = combined(old, incoming)
            if old == result:
                return
            new = {
                "PartitionKey": "runtime",
                "RowKey": sid,
                "value": json.dumps(result, separators=(",", ":")),
            }
            # Each attempt and last-success pair can exceed a single Table string's 64 KiB limit.
            if len(new["value"].encode("utf-16-le")) > 64000:
                raise ContractError(
                    "stored runtime evidence exceeds table property limit"
                )
            try:
                if entity:
                    self.table.update_entity(
                        new,
                        mode="replace",
                        etag=entity.metadata["etag"],
                        match_condition=MatchConditions.IfNotModified,
                    )
                else:
                    self.table.create_entity(new)
                return
            except (ResourceExistsError, ResourceModifiedError):
                continue
        raise RuntimeError("concurrent runtime observation updates; retry delivery")

    def rows(self):
        if self.table is None:
            with self.lock:
                return json.loads(json.dumps(self.memory))
        return {
            row["RowKey"]: json.loads(row["value"])
            for row in self.table.query_entities(
                "PartitionKey eq @pk", parameters={"pk": "runtime"}
            )
        }


def record(store, catalog, rows):
    ids = {}
    for server in catalog.get("servers", []):
        ids.setdefault(server.get("aws_instance_id"), []).append(server["id"])
    matched = unmatched = 0
    for row in rows:
        if "aws_ssm_node_id" in row["key"]:
            matches = [s["id"] for s in catalog.get("servers", []) if s.get("ssm_node_id") == row["key"]["aws_ssm_node_id"] and s.get("cellarum_item_id") == row["item_id"]]
        else:
            matches = ids.get(row["key"]["aws_instance_id"], [])
        if len(matches) != 1:
            unmatched += 1
            continue
        store.put(matches[0], row)
        matched += 1
    return {"matched": matched, "unmatched": unmatched}


def view(row, now):
    attempt, success = row.get("attempt"), row.get("success")
    if not attempt:
        return {
            "freshness": "unassessed",
            "components": [],
            "gaps": ["No runtime observation received"],
        }
    result = {
        "attempted_at": attempt["received_at"],
        "last_attempt": attempt["outcome"],
        "failure_reason": attempt["facts"].get("reason"),
    }
    if not success:
        return {
            **result,
            "freshness": "unavailable",
            "components": [],
            "gaps": ["Collection unavailable"],
        }
    fresh = now - time(success["observed_at"]) <= MAX_AGE
    facts = {key: value for key, value in success["facts"].items() if key != "openssh"}
    return {
        **result,
        **facts,
        "observed_at": success["observed_at"],
        "freshness": "fresh" if fresh and attempt["outcome"] == "accepted" else "stale",
        "item_id": success["item_id"],
        "observation_id": success["observation_id"],
    }
