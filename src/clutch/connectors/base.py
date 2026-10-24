"""Base connector interface — all connectors implement this."""

from __future__ import annotations

import abc
from typing import Any

from clutch.models import NormalizedEvent


class ClutchConnector(abc.ABC):
    """Base class for all Clutch connectors.

    Community connectors ship as `clutch-connector-*` packages
    and implement this interface.
    """

    name: str
    source_type: str  # "event" | "task" | "message"

    @abc.abstractmethod
    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        """Fetch and normalize events from this source."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return True if the connector can reach its source."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name}>"
