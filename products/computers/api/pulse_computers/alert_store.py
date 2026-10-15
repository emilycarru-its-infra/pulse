"""Persistent alert state and a lease preventing overlapping monitor runs."""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import TableClient, UpdateMode
from azure.identity import DefaultAzureCredential


class AlertState:
    def __init__(self, table):
        self.table = table
        self.records = None

    @classmethod
    def from_account(cls, account, name):
        endpoint = account if account.startswith("https://") else f"https://{account}.table.core.windows.net"
        return cls(TableClient(endpoint, name, credential=DefaultAzureCredential()))

    def get(self, key):
        if self.records is None:
            self.records = {row["RowKey"]: json.loads(row["data"]) for row in
                            self.table.query_entities("PartitionKey eq 'monitor'")}
        return self.records.get(key)

    def put(self, key, value):
        self.table.upsert_entity({"PartitionKey": "monitor", "RowKey": key,
                                  "data": json.dumps(value)}, mode=UpdateMode.REPLACE)
        if self.records is not None:
            self.records[key] = value

    @contextmanager
    def lease(self):
        now = datetime.now(timezone.utc)
        owner = uuid.uuid4().hex
        row = {"PartitionKey": "control", "RowKey": "lease", "owner": owner,
               "until": (now + timedelta(minutes=10)).isoformat()}
        try:
            self.table.create_entity(row)
        except ResourceExistsError:
            current = self.table.get_entity("control", "lease")
            if datetime.fromisoformat(current["until"]) > now:
                yield False
                return
            try:
                self.table.update_entity(row, mode=UpdateMode.REPLACE, etag=current.metadata["etag"],
                                         match_condition=MatchConditions.IfNotModified)
            except ResourceModifiedError:
                yield False
                return
        try:
            yield True
        finally:
            current = self.table.get_entity("control", "lease")
            if current.get("owner") == owner:
                self.table.delete_entity("control", "lease", etag=current.metadata["etag"],
                                         match_condition=MatchConditions.IfNotModified)
