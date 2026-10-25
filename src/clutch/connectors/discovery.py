"""Connector auto-discovery via Python entry points.

Any installed package that declares an entry point in the
"clutch.connectors" group is automatically discovered and
available to the pipeline.

Example entry point (in a connector's pyproject.toml):

    [project.entry-points."clutch.connectors"]
    rss = "clutch_connector_rss:RSSConnector"

The key ("rss") becomes the connector name used in clutch.yaml.
The value is the import path to the connector class.
"""

from __future__ import annotations

import sys
from typing import Any

from clutch.connectors.base import ClutchConnector

if sys.version_info >= (3, 12):
    from importlib.metadata import entry_points
else:
    from importlib_metadata import entry_points

ENTRY_POINT_GROUP = "clutch.connectors"


def discover_connector_classes() -> dict[str, type[ClutchConnector]]:
    """Find all installed connector classes.

    Returns a dict mapping connector name to class:
        {"rss": RSSConnector, "discord": DiscordConnector, ...}
    """
    connectors: dict[str, type[ClutchConnector]] = {}

    eps = entry_points(group=ENTRY_POINT_GROUP)
    for ep in eps:
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, ClutchConnector):
                connectors[ep.name] = cls
            else:
                print(f"[discovery] Skipping {ep.name}: not a ClutchConnector subclass")
        except Exception as e:
            print(f"[discovery] Failed to load connector '{ep.name}': {e}")

    return connectors


def list_available_connectors() -> list[dict[str, str]]:
    """List all discovered connectors with metadata.

    Returns:
        [{"name": "rss", "class": "RSSConnector", "source_type": "message"}, ...]
    """
    classes = discover_connector_classes()
    result = []
    for name, cls in sorted(classes.items()):
        result.append({
            "name": name,
            "class": cls.__name__,
            "module": cls.__module__,
            "source_type": getattr(cls, "source_type", "unknown"),
        })
    return result


def build_connectors_from_config(
    config: Any,
    env: Any,
) -> list[ClutchConnector]:
    """Instantiate enabled connectors based on clutch.yaml config.

    For each discovered connector, checks if it's enabled in the config
    and passes the relevant config section + env secrets to the constructor.
    """
    available = discover_connector_classes()
    instances: list[ClutchConnector] = []

    connectors_cfg = config.connectors if hasattr(config, "connectors") else {}

    for name, cls in available.items():
        # Skip internal connectors (template, mock)
        if name in ("template", "mock"):
            continue

        # Get connector-specific config
        connector_cfg = _get_connector_config(name, connectors_cfg)
        if connector_cfg is None:
            continue

        enabled = connector_cfg.get("enabled", False) if isinstance(connector_cfg, dict) else getattr(connector_cfg, "enabled", False)
        if not enabled:
            continue

        try:
            instance = _instantiate_connector(name, cls, connector_cfg, env)
            if instance:
                instances.append(instance)
        except Exception as e:
            print(f"[discovery] Failed to instantiate '{name}': {e}")

    return instances


def _get_connector_config(name: str, connectors_cfg: Any) -> Any:
    """Extract config for a specific connector from the connectors section."""
    # Try typed attribute first (discord, luma, rss)
    if hasattr(connectors_cfg, name) and not name.startswith("_"):
        val = getattr(connectors_cfg, name, None)
        if val is not None:
            return val
    # Then try extra fields (hacktoberfest, konfhub, etc. via model_config extra=allow)
    if hasattr(connectors_cfg, "model_extra"):
        extras = connectors_cfg.model_extra or {}
        if name in extras:
            return extras[name]
    # Fallback for plain dicts
    if isinstance(connectors_cfg, dict):
        return connectors_cfg.get(name)
    return None


def _instantiate_connector(
    name: str,
    cls: type[ClutchConnector],
    cfg: Any,
    env: Any,
) -> ClutchConnector | None:
    """Create a connector instance with the right kwargs."""
    # Convert pydantic model to dict if needed
    if hasattr(cfg, "model_dump"):
        kwargs = cfg.model_dump()
    elif isinstance(cfg, dict):
        kwargs = cfg.copy()
    else:
        kwargs = {}

    # Remove 'enabled' — connectors don't need it
    kwargs.pop("enabled", None)

    # Inject secrets from env for known connectors
    env_mappings = {
        "discord": {"token": "discord_token"},
        "github": {"token": "github_token"},
        "jira": {"url": "jira_url", "email": "jira_email", "api_token": "jira_api_token"},
    }

    if name in env_mappings:
        for kwarg_name, env_attr in env_mappings[name].items():
            if kwarg_name not in kwargs or not kwargs[kwarg_name]:
                value = getattr(env, env_attr, "")
                if value:
                    kwargs[kwarg_name] = value

    # Handle nested pydantic models (e.g. servers list)
    for key, val in kwargs.items():
        if isinstance(val, list):
            kwargs[key] = [
                v.model_dump() if hasattr(v, "model_dump") else v for v in val
            ]

    return cls(**kwargs)
