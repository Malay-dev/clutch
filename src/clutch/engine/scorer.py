"""Gemma scoring engine — scores events via Ollama.

Supports two modes:
- Single: one event per LLM call (original, more accurate)
- Batch: multiple events per LLM call (faster, fewer round-trips)
"""

from __future__ import annotations

import json
import re
from typing import Optional

import httpx

from clutch.config import ClutchConfig
from clutch.engine.prompts import (
    BATCH_SCORING_USER_PROMPT,
    SCORING_SYSTEM_PROMPT,
    SCORING_USER_PROMPT,
)
from clutch.models import NormalizedEvent, ScoredEvent, ScoringResult

# Default batch size — how many events per single LLM call
DEFAULT_BATCH_SIZE = 5


class GemmaScorer:
    """Scores events against user interests using Gemma via Ollama."""

    def __init__(self, config: ClutchConfig, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        self.config = config
        self.ollama_host = config.ollama.host.rstrip("/")
        self.model = config.ollama.model
        self.timeout = config.ollama.timeout
        self.batch_size = batch_size

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
            raw_text=event.raw_text[:1500],
        )

        result = await self._call_ollama(prompt)
        scoring = self._parse_response(result)
        return ScoredEvent.from_scoring(event, scoring)

    async def score_batch(self, events: list[NormalizedEvent]) -> list[ScoredEvent]:
        """Score events in batches for efficiency.

        Groups events into batches of self.batch_size and sends each
        batch as a single LLM call. Falls back to individual scoring
        if batch parsing fails.
        """
        scored: list[ScoredEvent] = []

        for i in range(0, len(events), self.batch_size):
            batch = events[i : i + self.batch_size]

            if len(batch) == 1:
                # Single event — use the more precise single prompt
                try:
                    se = await self.score(batch[0])
                    scored.append(se)
                except Exception as e:
                    print(f"[scorer] Failed to score '{batch[0].title}': {e}")
                    scored.append(self._fallback_score(batch[0], str(e)))
                continue

            # Batch scoring
            try:
                batch_results = await self._score_batch_call(batch)
                scored.extend(batch_results)
            except Exception as e:
                print(f"[scorer] Batch scoring failed, falling back to individual: {e}")
                # Fallback: score individually
                for event in batch:
                    try:
                        se = await self.score(event)
                        scored.append(se)
                    except Exception as e2:
                        scored.append(self._fallback_score(event, str(e2)))

        return scored

    async def _score_batch_call(self, batch: list[NormalizedEvent]) -> list[ScoredEvent]:
        """Score a batch of events in a single LLM call."""
        # Build the events block
        events_block = ""
        for idx, event in enumerate(batch, 1):
            deadline_str = event.deadline.isoformat() if event.deadline else "None"
            events_block += (
                f"### Event {idx}\n"
                f"Title: {event.title}\n"
                f"Source: {event.source}\n"
                f"Type: {event.event_type.value}\n"
                f"Deadline: {deadline_str}\n"
                f"Location: {event.location or 'Unknown'}\n"
                f"Content: {event.raw_text[:800]}\n\n"
            )

        prompt = BATCH_SCORING_USER_PROMPT.format(
            name=self.config.profile.name,
            location=self.config.profile.location,
            interests=", ".join(self.config.profile.interests),
            events_block=events_block,
        )

        result = await self._call_ollama(prompt, num_predict=len(batch) * 120, force_json=False)
        return self._parse_batch_response(result, batch)

    def _parse_batch_response(
        self, raw: str, batch: list[NormalizedEvent]
    ) -> list[ScoredEvent]:
        """Parse Gemma's batch JSON response into ScoredEvents."""
        # Try to parse as JSON array
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                results = []
                for idx, event in enumerate(batch):
                    if idx < len(data):
                        scoring = self._dict_to_scoring(data[idx])
                    else:
                        scoring = self._default_scoring("Batch response incomplete")
                    results.append(ScoredEvent.from_scoring(event, scoring))
                return results
        except json.JSONDecodeError:
            pass

        # Try to find a JSON array in the response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                results = []
                for idx, event in enumerate(batch):
                    if idx < len(data):
                        scoring = self._dict_to_scoring(data[idx])
                    else:
                        scoring = self._default_scoring("Batch response incomplete")
                    results.append(ScoredEvent.from_scoring(event, scoring))
                return results
            except json.JSONDecodeError:
                pass

        # Complete fallback — couldn't parse batch response
        raise ValueError(f"Could not parse batch response: {raw[:300]}")

    async def _call_ollama(self, prompt: str, num_predict: int = 300, force_json: bool = True) -> str:
        """Call Ollama's chat API."""
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": num_predict,
            },
        }
        if force_json:
            body["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.ollama_host}/api/chat",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

    def _parse_response(self, raw: str) -> ScoringResult:
        """Parse Gemma's JSON response into a ScoringResult."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Could not parse scoring response: {raw[:200]}")

        return self._dict_to_scoring(data)

    def _dict_to_scoring(self, data: dict) -> ScoringResult:
        """Convert a dict to ScoringResult."""
        return ScoringResult(
            interest_score=self._clamp(data.get("interest_score", 0.1)),
            urgency=self._clamp(data.get("urgency", 0.1)),
            scarcity=self._clamp(data.get("scarcity", 0.1)),
            impact=self._clamp(data.get("impact", 0.1)),
            reason=data.get("reason", "No reason provided"),
            action_required=data.get("action_required"),
        )

    def _default_scoring(self, reason: str) -> ScoringResult:
        return ScoringResult(
            interest_score=0.1,
            urgency=0.1,
            scarcity=0.1,
            impact=0.1,
            reason=reason,
            action_required=None,
        )

    def _fallback_score(self, event: NormalizedEvent, error: str) -> ScoredEvent:
        """Create a low-score fallback when scoring fails."""
        return ScoredEvent.from_scoring(event, self._default_scoring(f"Scoring failed: {error}"))

    @staticmethod
    def _clamp(value: float) -> float:
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
            return any(model in name or name.startswith(model) for name in model_names)
    except Exception:
        return False
