# CLUTCH

> **The AI that won't let you miss what matters.**
> Silently watches your communities. Surfaces what's critical. Nags you until it's done.

## The Problem

I missed GDG DevFest Bengaluru by one day. The ticket sold out while the
announcement sat unread in my Discord. I don't need more notifications —
I need something that knows what I can't afford to miss.

That's why I built Clutch.

## What It Does

Clutch is a local open-source AI agent that:

1. **Ingests** from Discord, Luma, RSS, GitHub, and more — every N hours
2. **Scores** each event against your personal interest profile using **Gemma 3** (local, via Ollama)
3. **Blocks** your Google Calendar with color-coded persistent reminders
4. **Escalates** daily until you mark it done — it will not stop
5. **Digests** into a 3-bullet morning brief

## Quick Start

### Prerequisites

- [Podman](https://podman.io/) installed
- [Ollama](https://ollama.ai/) with Gemma 3 pulled:
  ```bash
  ollama pull gemma3:4b
  ```
- Google Cloud project with Calendar API enabled

### Setup

```bash
# Clone
git clone https://github.com/malay-kumar/clutch.git
cd clutch

# Configure
cp .env.example .env
# Edit .env with your secrets
# Edit clutch.yaml with your interests

# Authenticate Google Calendar
clutch auth google

# Run once (demo mode)
podman compose run --rm clutch-once

# Run as daemon
podman compose up -d clutch
```

### Local Development

```bash
# Install with uv
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run locally
clutch run --once
```

## CLI Commands

```bash
clutch init               # scaffold clutch.yaml + .env
clutch auth google        # one-time OAuth
clutch run                # start daemon (APScheduler)
clutch run --once         # single pipeline run
clutch run --temporal     # use Temporal scheduler
clutch status             # event counts by priority
clutch radar              # terminal priority table
clutch done "DevFest"     # mark done, clear calendar
clutch digest             # morning brief
clutch menubar            # macOS menu bar app
```

## Architecture

```
Connectors (Discord, RSS, Luma)
    -> Normalization Engine
    -> Gemma Scoring (via Ollama, local)
    -> Priority Engine (Interest x Urgency x Scarcity x Impact)
    -> Google Calendar (escalating color-coded blocks)
    -> macOS Menu Bar (rumps)
```

## Calendar Escalation

Uses Google Calendar's native color system — no emojis. Colors escalate
automatically as deadlines approach:

```
Day 1  — Blue:      [INFO] GDG DevFest Bangalore
Day 3  — Orange:    [HIGH] GDG DevFest Bangalore [reminder]
Day 8  — Red:       [CRITICAL] GDG DevFest Bangalore [action needed]
Day 10 — Red:       [CRITICAL] GDG DevFest Bangalore [TODAY]

Mark done -> calendar chain cleared.
```

| Priority | Google Calendar Color | Color ID |
|----------|----------------------|----------|
| CRITICAL | Tomato (red)         | 11       |
| HIGH     | Tangerine (orange)   | 6        |
| INFO     | Blueberry (blue)     | 9        |

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | Python + Typer | Same language end-to-end |
| AI | Ollama + Gemma 3 | Local, open-weight, private |
| Storage | SQLite | Simple, zero config |
| Scheduler | APScheduler / Temporal | Durable, survives restarts |
| Calendar | Google Calendar API | Already on every phone |
| Menu Bar | rumps | ~50 lines, macOS native |
| Containers | Podman | Fully OSS, rootless |

## License

MIT
