"""Cheap pre-filter — eliminates obviously irrelevant events before Gemma.

This runs BEFORE the LLM. It uses simple keyword matching against the
user's interest profile to skip events that clearly don't belong.
No API calls, no inference — just string matching.

Events that pass the pre-filter go to Gemma for proper scoring.
Events that fail get a score of 0.0 and priority INFO automatically.
"""

from __future__ import annotations

import re
from clutch.config import ProfileConfig
from clutch.models import NormalizedEvent


def build_interest_patterns(profile: ProfileConfig) -> list[re.Pattern]:
    """Build regex patterns from the user's interest list."""
    patterns = []
    for interest in profile.interests:
        # Split compound interests like "AI/ML" into ["AI", "ML"]
        terms = re.split(r"[/,&+]", interest)
        for term in terms:
            term = term.strip()
            if len(term) >= 2:
                patterns.append(re.compile(re.escape(term), re.IGNORECASE))
    # Also add location as a pattern
    if profile.location:
        patterns.append(re.compile(re.escape(profile.location), re.IGNORECASE))
    return patterns


def prefilter_events(
    events: list[NormalizedEvent],
    profile: ProfileConfig,
    min_matches: int = 1,
) -> tuple[list[NormalizedEvent], list[NormalizedEvent]]:
    """Split events into relevant (send to Gemma) and noise (skip).

    Args:
        events: All normalized events.
        profile: User profile with interests and location.
        min_matches: Minimum keyword matches to pass the filter.

    Returns:
        (relevant, noise) — relevant goes to Gemma, noise gets auto-scored 0.0.
    """
    patterns = build_interest_patterns(profile)
    if not patterns:
        # No profile configured — send everything to Gemma
        return events, []

    relevant: list[NormalizedEvent] = []
    noise: list[NormalizedEvent] = []

    for event in events:
        searchable = f"{event.title} {event.raw_text} {event.location or ''}"
        match_count = sum(1 for p in patterns if p.search(searchable))

        if match_count >= min_matches:
            relevant.append(event)
        else:
            noise.append(event)

    return relevant, noise
