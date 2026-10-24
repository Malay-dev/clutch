"""Discord connector — reads announcement/event channels."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from clutch.connectors.base import ClutchConnector
from clutch.models import EventType, NormalizedEvent


class DiscordConnector(ClutchConnector):
    """Fetches recent messages from configured Discord servers/channels.

    Uses discord.py in a headless read-only mode. The bot must be
    invited to the target servers with message read permissions.
    """

    name = "discord"
    source_type = "message"

    def __init__(self, token: str, servers: list[dict]) -> None:
        self.token = token
        self.servers = servers  # [{"name": "...", "channels": [...]}]

    async def fetch(self, **kwargs: Any) -> list[NormalizedEvent]:
        """Fetch recent messages from configured channels."""
        import discord

        events: list[NormalizedEvent] = []
        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready() -> None:
            try:
                for server_cfg in self.servers:
                    server_name = server_cfg["name"]
                    target_channels = server_cfg.get("channels", [])

                    for guild in client.guilds:
                        if server_name.lower() not in guild.name.lower():
                            continue
                        for channel in guild.text_channels:
                            if target_channels and channel.name not in target_channels:
                                continue
                            try:
                                async for message in channel.history(limit=30):
                                    if message.author.bot:
                                        continue
                                    events.append(
                                        self._normalize(message, guild.name, channel.name)
                                    )
                            except discord.Forbidden:
                                print(f"[discord] No access to #{channel.name} in {guild.name}")
            finally:
                await client.close()

        await client.start(self.token)
        return events

    async def health_check(self) -> bool:
        return bool(self.token)

    def _normalize(self, message: Any, guild_name: str, channel_name: str) -> NormalizedEvent:
        msg_id = hashlib.sha256(f"{message.id}".encode()).hexdigest()[:16]
        content = message.content or ""
        embeds_text = ""
        for embed in message.embeds:
            if embed.title:
                embeds_text += f"\n{embed.title}"
            if embed.description:
                embeds_text += f"\n{embed.description}"

        full_text = f"{content}{embeds_text}".strip()
        title = full_text[:120] if full_text else "Discord message"

        return NormalizedEvent(
            id=f"discord:{msg_id}",
            title=title,
            source="discord",
            source_url=message.jump_url if hasattr(message, "jump_url") else None,
            raw_text=full_text,
            event_type=EventType.ANNOUNCEMENT,
            deadline=None,
            fetched_at=datetime.now(),
            metadata={
                "guild": guild_name,
                "channel": channel_name,
                "author": str(message.author),
                "message_id": str(message.id),
            },
        )
