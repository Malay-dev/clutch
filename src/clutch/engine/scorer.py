"""Gemma scoring engine — scores events via Ollama."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

import httpx

from clutch.config import ClutchConfig
from clutch.engine.prompts import SCORING_SYSTEM_PROMPT, SCORING_USER_PROMPT
from clutch.models import NormalizedEvent, ScoredEvent, ScoringResult


class GemmaScorer:
    """Scores events against user interests using Gemma via Ollama."""

    def __init__(self, config: ClutchConfig) -> None:
        self.config = config
        self.ollama_host = config.ollama.host.rstrip("/")
        self.model = config.ollama.model
        self.timeout = config.ollama.timeout

    async def score(self, event: NormalizedEvent) -> ScoredEvent:
        """Score a single event and return a ScoredEvent."""
        prompt = SCORING_USER_PROMPT.format(
            name=self.config.profile.name,
            location=self.config.profile.location,
            interests=", ".join(self.config.profile.interests),
            title=event.title,
            source=event.source,
            event_type=event.event_type.value,
            deadline=event.deadline.isoformat() if event.deadline else "None",
            event_location=event.location or "Unknown",
            raw_text=event.raw_text[:1500],  # cap context length
        )

        result = await self._call_ollama(prompt)
        scoring = self._parse_response(result)
        return ScoredEvent.from_scoring(event, scoring)

    async def score_batch(self, events: list[NormalizedEvent]) -> list[ScoredEvent]:
        """Score a batch of events sequentially."""
        scored: list[ScoredEvent] = []
        for event in events:
            try:
                se = await self.score(event)
                scored.append(se)
            except Exception as e:
                print(f"[scorer] Failed to score '{event.title}': {e}")
                # Assign a low default score so the event isn't lost
                fallback = ScoringResult(
                    interest_score=0.1,
                    urgency=0.1,
                    scarcity=0.1,
                    impact=0.1,
                    reason=f"Scoring failed: {e}",
                    action_required=None,
                )
                scored.append(ScoredEvent.from_scoring(event, fallback))
        return scored

    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama's generate API."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.ollama_host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,  # low temp for consistent scoring
                        "num_predict": 300,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

    def _parse_response(self, raw: str) -> ScoringResult:
        """Parse Gemma's JSON response into a ScoringResult."""
        # Try to extract JSON from the response
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Could not parse scoring response: {raw[:200]}")

        return ScoringResult(
            interest_score=self._clamp(data.get("interest_score", 0.1)),
            urgency=self._clamp(data.get("urgency", 0.1)),
            scarcity=self._clamp(data.get("scarcity", 0.1)),
            impact=self._clamp(data.get("impact", 0.1)),
            reason=data.get("reason", "No reason provided"),
            action_required=data.get("action_required"),
        )

    @staticmethod
    def _clamp(value: float) -> float:
        """Clamp a value between 0 and 1."""
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.1


async def check_ollama(host: str, model: str) -> bool:
    """Check if Ollama is running and the model is available."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{host}/api/tags")
            if resp.status_code != 200:
                return False
            data = resp.json()
            model_names = [m["name"] for m in data.get("models", [])]
            # Check for exact match or prefix match (e.g. "gemma3:4b" matches "gemma3:4b")
            return any(model in name or name.startswith(model) for name in model_names)
    except Exception:
        return False
