# clutch-connector-hacktoberfest

Hacktoberfest events connector for [Clutch](https://github.com/malay-kumar/clutch). Fetches hack days, meetups, and online events from [hacktoberfest.com](https://hacktoberfest.com).

## Install

```bash
pip install clutch-connector-hacktoberfest
```

## Config

```yaml
# clutch.yaml
connectors:
  hacktoberfest:
    enabled: true
    countries: [IN]              # ISO country codes, empty = all countries
    cities: [Bengaluru]          # filter by city name, empty = all cities
    include_ended: false         # skip past events
    include_online: true         # include online streams and ceremonies
```

No API key needed — uses the public MLH events API.

## What It Fetches

- Hack days (in-person one-day hackathons)
- Meetups (community gatherings)
- Online streams, workshops, and ceremonies
- For each event: title, description, date, location, registration URL, format

## Data Source

Public API: `https://hacktoberfest-api.mlh.com/api/events`

Same data rendered on https://hacktoberfest.com/schedule/ and https://hacktoberfest.com/fests/.

## License

MIT
