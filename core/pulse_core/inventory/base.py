from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class Device:
    """One device as the inventory knows it. Every provider returns these."""

    hostname: str
    asset_tag: str
    serial: str
    platform: str
    category: str
    location: str
    group: str
    deployed: bool
    name: str = ""  # what the inventory calls the device, such as "FMSA Control Room"
    device_ids: tuple[str, ...] = ()  # management ids its certificates carry (Intune, Entra), lowercase


class InventoryProvider(Protocol):
    name: str

    def devices(self) -> Iterable[Device]: ...
