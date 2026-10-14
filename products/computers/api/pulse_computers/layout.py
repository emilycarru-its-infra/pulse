"""Durable seat overrides, applied over the inventory-built catalog."""

import json
import math
import threading
from copy import deepcopy


class LayoutConflict(Exception):
    """Another editor saved since the caller loaded the layout."""


class MemoryLayouts:
    def __init__(self):
        self.positions = {}
        self.version = 0
        self.lock = threading.Lock()

    def read(self):
        with self.lock:
            return deepcopy(self.positions), str(self.version)

    def write(self, positions, version):
        with self.lock:
            if version != str(self.version):
                raise LayoutConflict
            self.positions = deepcopy(positions)
            self.version += 1
            return str(self.version)


class TableLayouts:
    def __init__(self, table):
        self.table = table

    @classmethod
    def from_account(cls, account, name):
        from azure.data.tables import TableClient
        from azure.identity import DefaultAzureCredential

        endpoint = account if account.startswith("https://") else f"https://{account}.table.core.windows.net"
        return cls(TableClient(endpoint, name, credential=DefaultAzureCredential()))

    def read(self):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            row = self.table.get_entity("layout", "seats")
        except ResourceNotFoundError:
            return {}, "0"
        return json.loads(row["positions"]), row.metadata["etag"]

    def write(self, positions, version):
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError

        body = json.dumps(positions, separators=(",", ":"), sort_keys=True)
        if len(body.encode()) > 60_000:
            raise ValueError("the saved layout is too large")
        # Binary stores the UTF-8 JSON without the smaller UTF-16 string-property limit.
        row = {"PartitionKey": "layout", "RowKey": "seats", "positions": body.encode()}
        try:
            if version == "0":
                result = self.table.create_entity(row)
            else:
                result = self.table.update_entity(row, mode="replace", etag=version,
                                                 match_condition=MatchConditions.IfNotModified)
        except (ResourceExistsError, ResourceModifiedError, ResourceNotFoundError) as e:
            raise LayoutConflict from e
        return result["etag"]


def apply_positions(status, positions):
    for space in status["spaces"]:
        for seat in space["seats"]:
            position = positions.get(seat["hostname"].upper())
            if position is not None and position["floor"] == space.get("floor"):
                seat["x"], seat["y"] = position["x"], position["y"]
    return status


def validate_moves(catalog, moves):
    if not isinstance(moves, dict) or not moves:
        raise ValueError("send {hostname: [x, y]}")
    floors = {floor["id"]: floor for floor in catalog.get("floors", [])}
    seats = {seat["hostname"].upper(): floors.get(space.get("floor"))
             for space in catalog["spaces"] for seat in space["seats"]}
    valid = {}
    for host, xy in moves.items():
        floor = seats.get(host.upper())
        if floor is None:
            raise ValueError(f"{host} is not a seat on a plan")
        if host.upper() in valid:
            raise ValueError(f"{host} is named twice")
        if not (isinstance(xy, list) and len(xy) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in xy)):
            raise ValueError(f"{host}: position must be [x, y]")
        x, y = xy
        if not (0 <= x <= floor["width"] and 0 <= y <= floor["height"]):
            raise ValueError(f"{host}: position must be inside its floor plan")
        valid[host.upper()] = {"floor": floor["id"], "x": round(x, 1), "y": round(y, 1)}
    return valid
