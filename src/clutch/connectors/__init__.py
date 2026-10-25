"""Clutch connector SDK — base class and auto-discovery.

Connectors are separate packages that register via entry points.
Install them with: pip install clutch-connector-{name}

Available connectors:
    clutch-connector-rss      — RSS/Atom feeds
    clutch-connector-discord  — Discord servers
    clutch-connector-luma     — Luma events

Build your own: see connectors/template/
"""

from clutch.connectors.base import ClutchConnector
from clutch.connectors.discovery import (
    build_connectors_from_config,
    discover_connector_classes,
    list_available_connectors,
)

__all__ = [
    "ClutchConnector",
    "build_connectors_from_config",
    "discover_connector_classes",
    "list_available_connectors",
]
