"""Adaptive Card delivery through an Entra-authenticated relay. No shared keys."""

import json
import logging
import urllib.request

from azure.identity import DefaultAzureCredential


class Relay:
    def __init__(self, url, audience, channel, team="", credential=None):
        if not url.startswith("https://") or not audience or not channel:
            raise ValueError("configure an HTTPS relay, audience and channel")
        self.url, self.audience, self.channel, self.team = url, audience, channel, team
        self.credential = credential or DefaultAzureCredential()

    def __call__(self, card):
        token = self.credential.get_token(f"{self.audience}/.default").token
        payload = {"channel": self.channel, "card": card}
        if self.team:
            payload["team"] = self.team
        req = urllib.request.Request(self.url, method="POST", data=json.dumps(payload).encode(),
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.load(response)
        if not result.get("ok") or result.get("channel", "").lower() != self.channel.lower():
            raise RuntimeError("relay did not confirm delivery to the requested channel")

        logging.warning("Beacon alert delivered to %s via %s", self.channel, result.get("via", "unknown"))
