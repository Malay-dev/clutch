# clutch-connector-template

Starter template for building a Clutch connector.

## Quick Start

```bash
# 1. Copy this template
cp -r connectors/template connectors/my-source

# 2. Rename the package
mv connectors/my-source/src/clutch_connector_template \
   connectors/my-source/src/clutch_connector_mysource

# 3. Update pyproject.toml
#    - name = "clutch-connector-mysource"
#    - entry point: mysource = "clutch_connector_mysource:MySourceConnector"

# 4. Implement fetch() and health_check() in connector.py

# 5. Install in dev mode
pip install -e connectors/my-source

# 6. Clutch auto-discovers it
clutch run --once
```

## Connector Interface

Every connector implements two methods:

```python
class MySourceConnector(ClutchConnector):
    name = "mysource"
    source_type = "event"  # "event" | "task" | "message"

    async def fetch(self, **kwargs) -> list[NormalizedEvent]:
        """Fetch and normalize events from your source."""
        ...

    async def health_check(self) -> bool:
        """Return True if the source is reachable."""
        ...
```

## NormalizedEvent Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | str | Yes | Unique stable ID: `{source}:{hash}` |
| title | str | Yes | Short display title |
| source | str | Yes | Connector name (must match `self.name`) |
| raw_text | str | Yes | Full text — Gemma scores based on this |
| event_type | EventType | Yes | EVENT, TASK, MESSAGE, DEADLINE, ANNOUNCEMENT |
| deadline | datetime | No | Expiry date — drives urgency scoring |
| location | str | No | Where it happens — helps location scoring |
| source_url | str | No | Link to original — included in calendar |
| metadata | dict | No | Extra data for your connector |

## Config

Add your connector's config section to `clutch.yaml`:

```yaml
connectors:
  mysource:
    enabled: true
    api_key: "your-key"
    # ... your connector-specific config
```

Secrets go in `.env`:

```bash
MYSOURCE_API_KEY=your-key-here
```

## Testing

Use the sandbox to test without real API calls:

```bash
clutch sandbox connectors --source mysource
```

## Publishing

Name your package `clutch-connector-{name}` and publish to PyPI.
Users install with `pip install clutch-connector-{name}`.
Clutch auto-discovers via entry points — no config changes needed.
