"""Aggregates year+event mentions scraped from the website (and news dates)
into a de-duplicated, importance-ranked company timeline."""
from __future__ import annotations

import re
from typing import List

from database.schema import TimelineEvent
from utils.dedupe import dedupe_strings

_HIGH_IMPORTANCE = (
    "founded", "found", "established", "acquisition", "acquired", "merger",
    "ipo", "went public", "listed on", "headquartered", "launched", "launch",
    "first ", "milestone", "spun off", "spin-off", "rebrand",
)
_MEDIUM_IMPORTANCE = ("expand", "opened", "award", "partnership", "appointed", "named")


def _score_importance(event_text: str) -> str:
    low = event_text.lower()
    if any(kw in low for kw in _HIGH_IMPORTANCE):
        return "high"
    if any(kw in low for kw in _MEDIUM_IMPORTANCE):
        return "medium"
    return "low"


def build_timeline(website_pages: List[dict], news_items: List[dict]) -> List[dict]:
    """Merge every (year, event-sentence) pair found across the site and
    news coverage, drop near-duplicate sentences per year, and rank each
    surviving event's importance."""
    events: List[TimelineEvent] = []

    for page in website_pages:
        for mention in page.get("timeline_mentions", []):
            events.append(
                TimelineEvent(
                    year=mention["year"],
                    event=mention["event"],
                    importance=_score_importance(mention["event"]),
                    source=page.get("url", ""),
                )
            )

    year_re = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
    for item in news_items:
        text = f"{item.get('headline', '')}. {item.get('summary', '')}"
        for year in set(year_re.findall(text)):
            events.append(
                TimelineEvent(
                    year=int(year),
                    event=item.get("headline", ""),
                    importance=_score_importance(text),
                    source=item.get("url", ""),
                )
            )

    # De-dupe near-identical event text within the same year.
    by_year: dict[int, list[TimelineEvent]] = {}
    for e in events:
        by_year.setdefault(e.year, []).append(e)

    final: List[dict] = []
    for year, yr_events in by_year.items():
        texts = dedupe_strings([e.event for e in yr_events], min_len=10)
        text_to_event = {e.event.strip(): e for e in yr_events}
        for t in texts:
            ev = text_to_event.get(t)
            if ev:
                final.append(ev.__dict__)

    final.sort(key=lambda e: (e["year"], {"high": 0, "medium": 1, "low": 2}[e["importance"]]))
    return final
