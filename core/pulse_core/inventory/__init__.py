"""Inventory providers: where the list of devices, rooms and groups comes from."""

from .base import Device, InventoryProvider
from .snipeit import SnipeItProvider

PROVIDERS = {"snipeit": SnipeItProvider}

__all__ = ["Device", "InventoryProvider", "PROVIDERS", "SnipeItProvider"]
