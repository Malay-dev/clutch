"""Morning digest — 3-bullet summary via Gemma."""

from __future__ import annotations

from datetime import datetime

import httpx

from clutch.config import ClutchConfig
from clutch.models import ScoredEvent


DIGEST_PROMPT = """\
You are Clutch, a personal priorities assistant. Generate a morning briefing.

## Today's Items (sorted by priority)
{items}

## Instructions
Write exactly 3 bullets in this format:
ACT NOW: [most urgent item — what to do and why]
THIS WEEK: [important but not immediate]
FYI: [interesting but no action needed]

If there are no items in a category, write "Nothing here — enjoy the calm."
Keep each bullet to one sentence. Be direct, not corporate. No emojis."""


async def generate_digest(
    events: list[ScoredEvent], config: ClutchConfig
) -> str:
    """Generate a 3-bullet morning digest from scored events."""
    if not events:
        return (
            "Clutch Morning Brief\n\n"
            "ACT NOW: Nothing — enjoy the calm.\n"
            "THIS WEEK: Nothing pending.\n"
            "FYI: All clear. Go build something."
        )

    items_text = ""
    for se in events[:10]:
        deadline_str = se.event.deadline.strftime("%b %d") if se.event.deadline else "no deadline"
        items_text += (
            f"- [{se.priority.value.upper()}] {se.event.title} "
            f"(score: {se.final_score:.2f}, deadline: {deadline_str})\n"
            f"  Reason: {se.scoring.reason}\n"
        )

    prompt = DIGEST_PROMPT.format(items=items_text)

    try:
        async with httpx.AsyncClient(timeout=config.ollama.timeout) as client:
            resp = await client.post(
                f"{config.ollama.host.rstrip('/')}/api/chat",
                json={
                    "model": config.ollama.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 200},
                },
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            return f"Clutch Morning Brief — {datetime.now().strftime('%b %d')}\n\n{content}"
    except Exception as e:
        # Fallback: generate without LLM
        brief = f"Clutch Morning Brief — {datetime.now().strftime('%b %d')}\n\n"
        critical = [ev for ev in events if ev.priority.value == "critical"]
        high = [ev for ev in events if ev.priority.value == "high"]
        info = [ev for ev in events if ev.priority.value == "info"]

        brief += f"ACT NOW: {critical[0].event.title}\n" if critical else "ACT NOW: Nothing urgent.\n"
        brief += f"THIS WEEK: {high[0].event.title}\n" if high else "THIS WEEK: All clear.\n"
        brief += f"FYI: {info[0].event.title}\n" if info else "FYI: Nothing noteworthy.\n"
        return brief
