"""News collector: queries Google News RSS (no API key needed) for a set of
company-related search terms, then uses newspaper3k as a best-effort way to
pull a fuller summary out of each article page.
"""
from __future__ import annotations

import asyncio
import html
import re
from typing import List, Optional
from urllib.parse import quote_plus

import feedparser

from config import NewsConfig
from database.schema import NewsItem
from utils.checkpoint import Checkpoint
from utils.dedupe import dedupe_dicts
from utils.http_client import AsyncHTTPClient
from utils.logging_config import get_logger

logger = get_logger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _rss_url(query: str, cfg: NewsConfig) -> str:
    q = quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl={cfg.language}&gl={cfg.country}&ceid={cfg.country}:{cfg.language.split('-')[0]}"


def _clean_summary(raw: str) -> str:
    return html.unescape(_TAG_RE.sub("", raw or "")).strip()


def _try_newspaper_summary(url: str) -> str:
    """Best-effort full-article summary via newspaper3k. Returns "" on any
    failure (paywalls, JS-only pages, network blocks, etc.)."""
    try:
        from newspaper import Article

        article = Article(url)
        article.download()
        article.parse()
        try:
            article.nlp()
            if article.summary:
                return article.summary.strip()
        except Exception:  # noqa: BLE001 - nlp() needs nltk data; fall back to raw text
            pass
        return " ".join(article.text.split()[:80])
    except Exception:  # noqa: BLE001
        return ""


async def _collect_query(client: AsyncHTTPClient, query: str, cfg: NewsConfig, checkpoint: Checkpoint) -> List[dict]:
    url = _rss_url(query, cfg)
    resp = await client.get(url)
    if resp is None:
        return []

    feed = feedparser.parse(resp.text)
    items: List[dict] = []

    for entry in feed.entries[: cfg.max_articles_per_query]:
        link = entry.get("link", "")
        if not link or checkpoint.is_done(link):
            continue

        summary = _clean_summary(entry.get("summary", ""))
        publication = ""
        if "source" in entry and hasattr(entry.source, "title"):
            publication = entry.source.title
        elif " - " in entry.get("title", ""):
            publication = entry["title"].rsplit(" - ", 1)[-1]

        full_summary = await asyncio.to_thread(_try_newspaper_summary, link)

        record = NewsItem(
            headline=_clean_summary(entry.get("title", "")),
            summary=full_summary or summary,
            publication=publication,
            date=entry.get("published", ""),
            url=link,
            query=query,
        )
        items.append(record.__dict__)
        checkpoint.mark_done(link)

    return items


async def scrape_news(company: str, queries: List[str], config: Optional[NewsConfig] = None) -> List[dict]:
    """Run every search query against Google News RSS concurrently and
    return the combined, de-duplicated list of articles."""
    cfg = config or NewsConfig()
    checkpoint = Checkpoint(company, "news")
    results: List[dict] = checkpoint.get_state("results", [])

    async with AsyncHTTPClient(rate_limit_delay=0.5) as client:
        batches = await asyncio.gather(*[_collect_query(client, q, cfg, checkpoint) for q in queries])

    for batch in batches:
        results.extend(batch)

    results = dedupe_dicts(results, "url")
    checkpoint.set_state("results", results)
    logger.info("News collection complete: %d articles across %d queries", len(results), len(queries))
    return results
