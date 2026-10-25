# clutch-connector-konfhub

KonfHub events connector for [Clutch](https://github.com/malay-kumar/clutch). Fetches conferences, hackathons, workshops, and meetups from [konfhub.com](https://konfhub.com).

## Install

```bash
pip install clutch-connector-konfhub
```

## Config

```yaml
# clutch.yaml
connectors:
  konfhub:
    enabled: true
    countries: [India]         # country names as shown on KonfHub
    cities: [Bengaluru]        # filter by city, empty = all cities
    include_paid: true         # include paid events
```

No API key needed — uses KonfHub's public featured-events API.

## What It Fetches

- Featured events on KonfHub (conferences, hackathons, workshops, meetups)
- Filters by country, city, and free/paid
- Skips past events automatically
- For each event: title, date, city, venue, free/paid, virtual flag, registration URL

## License

MIT
