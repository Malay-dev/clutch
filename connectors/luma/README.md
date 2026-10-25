# clutch-connector-luma

Luma events connector for [Clutch](https://github.com/malay-kumar/clutch). Fetches upcoming events from [lu.ma](https://lu.ma).

## Install

```bash
pip install clutch-connector-luma
```

## Config

```yaml
# clutch.yaml
connectors:
  luma:
    enabled: true
    cities: [Bengaluru, Remote, San Francisco]
    categories: [tech, ai, developer]
```

No API key needed — uses Luma's public event discovery API.

## What It Fetches

- Public events by city and category
- Extracts: title, description, start time, location, cover image, hosts
- Falls back to discover API if search endpoint is unavailable

## License

MIT
