"""Opt-in public source connectors; never import Gold or scoring machinery."""
from typing import Protocol


class PublicConnector(Protocol):
    """A server-configured source supplies normalized records, not routing decisions."""

    def execute(self, api: str, params: dict, cutoff: str) -> dict: ...
