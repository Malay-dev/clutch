# clutch-connector-discord

Discord connector for [Clutch](https://github.com/malay-kumar/clutch). Reads announcement and event channels from configured servers.

## Install

```bash
pip install clutch-connector-discord
```

## Setup

1. Create a Discord bot at https://discord.com/developers/applications
2. Enable "Message Content Intent" under Bot settings
3. Invite the bot to your target servers with Read Messages permission
4. Add the token to `.env`

## Config

```yaml
# clutch.yaml
connectors:
  discord:
    enabled: true
    servers:
      - name: GDG Bangalore
        channels: [announcements, events]
      - name: Hackerspace BLR
        channels: []  # empty = all channels
```

```bash
# .env
DISCORD_TOKEN=your-bot-token
```

## What It Fetches

- Last 30 messages per channel (non-bot only)
- Extracts message content + embed titles/descriptions
- Matches servers by name (substring, case-insensitive)

## License

MIT
