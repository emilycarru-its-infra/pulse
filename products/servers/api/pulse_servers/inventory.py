"""Read-only inventory projection, keyed by source item identity and item version."""

import json
import threading
from datetime import timedelta
from uuid import UUID

from .runtimes import ContractError, time

CONTRACT = "pulse.server-inventory/1"


def parse(body, now):
    if not isinstance(body, dict) or body.get("contract") != CONTRACT:
        raise ContractError("unsupported inventory projection contract")
    retrieved = time(body.get("retrieved_at"))
    if retrieved > now + timedelta(minutes=2):
        raise ContractError("inventory retrieval time is in the future")
    rows = body.get("servers")
    if not isinstance(rows, list) or len(rows) > 500:
        raise ContractError("inventory rows must be bounded")
    seen, result = set(), []
    for row in rows:
        try:
            if not isinstance(row, dict) or set(row) != {
                "item_id",
                "version",
                "service_group",
            }:
                raise ValueError()
            uid = str(UUID(row["item_id"]))
            version, group = row["version"], row["service_group"]
            if uid in seen or type(version) is not int or version < 1:
                raise ValueError()
            if group is not None and (
                not isinstance(group, str) or len(group) > 100 or "\x00" in group
            ):
                raise ValueError()
            seen.add(uid)
            result.append(
                {
                    "item_id": uid,
                    "version": version,
                    "service_group": group.strip() or None
                    if group is not None
                    else None,
                    "retrieved_at": body["retrieved_at"],
                }
            )
        except (ValueError, KeyError, TypeError):
            raise ContractError("invalid inventory row") from None
    return result


def combined(old, new):
    if old:
        if old["item_id"] != new["item_id"]:
            raise ContractError("inventory binding changed")
        if new["version"] < old["version"]:
            return old
        if new["version"] == old["version"]:
            if new["service_group"] != old["service_group"]:
                raise ContractError("conflicting values for one inventory version")
            if time(new["retrieved_at"]) <= time(old["retrieved_at"]):
                return old
    return new


class Store:
    def __init__(self, table=None):
        self.table, self.memory, self.lock = table, {}, threading.Lock()

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
                entity = self.table.get_entity("inventory", sid)
            except ResourceNotFoundError:
                entity = None
            old = json.loads(entity["value"]) if entity else None
            value = combined(old, incoming)
            if value == old:
                return
            new = {
                "PartitionKey": "inventory",
                "RowKey": sid,
                "value": json.dumps(value),
            }
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
        raise RuntimeError("concurrent inventory update; retry delivery")

    def rows(self):
        if self.table is None:
            with self.lock:
                return json.loads(json.dumps(self.memory))
        return {
            r["RowKey"]: json.loads(r["value"])
            for r in self.table.query_entities(
                "PartitionKey eq @pk", parameters={"pk": "inventory"}
            )
        }


def record(store, catalog, rows):
    by_id = {}
    for server in catalog.get("servers", []):
        uid = server.get("cellarum_item_id")
        if uid:
            if uid in by_id:
                raise ContractError("ambiguous inventory binding in site catalog")
            by_id[uid] = server["id"]
    matched = outside = 0
    for row in rows:
        sid = by_id.get(row["item_id"])
        if sid is None:
            outside += 1
            continue
        store.put(sid, row)
        matched += 1
    return {
        "matched": matched,
        "outside_catalog": outside,
        "unbound_catalog": [
            s["id"] for s in catalog.get("servers", []) if not s.get("cellarum_item_id")
        ],
    }
