#!/usr/bin/env python3
"""Company Trivia Intelligence System — single-command pipeline.

    python main.py --company "Galderma" \\
        --website https://www.galderma.com \\
        --instagram galdermaskincare \\
        --youtube "https://www.youtube.com/@Galderma"

Runs every scraper concurrently, derives the structured knowledge base
(products, timeline, leaders, facts), generates the quiz bank, and builds
the FAISS semantic search index — all resumable via per-stage checkpoints.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import time
from typing import List, Optional

from config import PipelineConfig
from database.knowledge_base import KnowledgeBase
from embeddings.embedder import SemanticIndex
from parsers.fact_extractor import build_facts
from parsers.leadership_extractor import build_leaders
from parsers.product_extractor import build_products
from parsers.timeline_builder import build_timeline
from quiz.quiz_generator import generate_quiz
from scrapers.instagram_scraper import scrape_instagram
from scrapers.news_scraper import scrape_news
from scrapers.website_scraper import scrape_website
from scrapers.youtube_scraper import scrape_youtube
from utils.logging_config import get_logger

logger = get_logger(__name__, company=None)


def _strip_raw_text(pages: List[dict]) -> List[dict]:
    """website.json shouldn't duplicate the multi-KB raw_text field already
    persisted per-page as markdown; keep the structured extraction only."""
    trimmed = []
    for page in pages:
        p = copy.copy(page)
        p.pop("raw_text", None)
        trimmed.append(p)
    return trimmed


async def _run_website(cfg: PipelineConfig, kb: KnowledgeBase) -> List[dict]:
    if "website" in cfg.skip or not cfg.website:
        logger.info("Skipping website scraping.")
        return kb.load("website_full", default=[])
    pages = await scrape_website(cfg.company, cfg.website, cfg.crawl)
    kb.save("website_full", pages)  # internal cache incl. raw_text, used by extractors below
    kb.save("website", _strip_raw_text(pages))
    return pages


async def _run_instagram(cfg: PipelineConfig, kb: KnowledgeBase) -> List[dict]:
    if "instagram" in cfg.skip or not cfg.instagram_handle:
        logger.info("Skipping Instagram scraping.")
        return kb.load("instagram", default=[])
    posts = await scrape_instagram(cfg.company, cfg.instagram_handle, cfg.instagram)
    kb.save("instagram", posts)
    return posts


async def _run_youtube(cfg: PipelineConfig, kb: KnowledgeBase) -> List[dict]:
    if "youtube" in cfg.skip or not cfg.youtube_channel:
        logger.info("Skipping YouTube scraping.")
        return kb.load("youtube", default=[])
    videos = await scrape_youtube(cfg.company, cfg.youtube_channel, cfg.youtube)
    kb.save("youtube", videos)
    return videos


async def _run_news(cfg: PipelineConfig, kb: KnowledgeBase) -> List[dict]:
    if "news" in cfg.skip:
        logger.info("Skipping news collection.")
        return kb.load("news", default=[])
    items = await scrape_news(cfg.company, cfg.news_queries, cfg.news)
    kb.save("news", items)
    return items


def _build_derived_knowledge(cfg: PipelineConfig, kb: KnowledgeBase, website_pages: List[dict], news_items: List[dict]) -> None:
    """Turn raw scraped pages + news into products/timeline/leaders/facts."""
    logger.info("Deriving structured knowledge base from scraped content...")

    products = build_products(cfg.company, website_pages, news_items)
    kb.save("products", products)

    timeline = build_timeline(website_pages, news_items)
    kb.save("timeline", timeline)

    leaders = build_leaders(website_pages)
    kb.save("leaders", leaders)

    facts = build_facts(website_pages, news_items, products, leaders, timeline)
    kb.save("facts", facts)


def _build_quiz(cfg: PipelineConfig, kb: KnowledgeBase) -> None:
    if "quiz" in cfg.skip:
        logger.info("Skipping quiz generation.")
        return
    quiz = generate_quiz(
        cfg.company,
        facts=kb.load("facts", default=[]),
        products=kb.load("products", default=[]),
        timeline=kb.load("timeline", default=[]),
        leaders=kb.load("leaders", default=[]),
        config=cfg.quiz,
    )
    kb.save("quiz", quiz)


def _build_embeddings(cfg: PipelineConfig) -> None:
    if "embeddings" in cfg.skip:
        logger.info("Skipping semantic index build.")
        return
    index = SemanticIndex(cfg.company, cfg.embedding)
    index.build()


async def run_pipeline(cfg: PipelineConfig) -> None:
    start = time.monotonic()
    kb = KnowledgeBase(cfg.company)

    logger.info("=" * 70)
    logger.info("Company Trivia Intelligence Pipeline — %s", cfg.company)
    logger.info("=" * 70)

    # Website, Instagram, YouTube, and News are fully independent — run them
    # concurrently rather than one after another.
    website_pages, instagram_posts, youtube_videos, news_items = await asyncio.gather(
        _run_website(cfg, kb),
        _run_instagram(cfg, kb),
        _run_youtube(cfg, kb),
        _run_news(cfg, kb),
    )

    _build_derived_knowledge(cfg, kb, website_pages, news_items)
    _build_quiz(cfg, kb)
    _build_embeddings(cfg)

    elapsed = time.monotonic() - start
    logger.info("Pipeline finished in %.1fs. Knowledge base summary:", elapsed)
    for key, count in kb.summary().items():
        logger.info("  %-12s %d records", key, count)
    logger.info("Data written to: %s", kb.dir)
    logger.info("Try: python ask.py --company \"%s\"", cfg.company)
    logger.info("Try: streamlit run dashboard/app.py")


def _guess_website(company: str) -> str:
    from slugify import slugify

    return f"https://www.{slugify(company)}.com"


def build_config_from_args(args: argparse.Namespace) -> PipelineConfig:
    cfg = PipelineConfig(
        company=args.company,
        website=args.website or _guess_website(args.company),
        instagram_handle=args.instagram,
        youtube_channel=args.youtube,
        news_queries=args.news_query or [],
        skip=set(args.skip or []),
    )
    if args.max_pages:
        cfg.crawl.max_pages = args.max_pages
    if args.max_depth:
        cfg.crawl.max_depth = args.max_depth
    return cfg


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a searchable trivia knowledge base for a company.")
    parser.add_argument("--company", required=True, help='Company name, e.g. "Galderma".')
    parser.add_argument("--website", help="Official website URL (guessed from the company name if omitted).")
    parser.add_argument("--instagram", help="Instagram handle, without the @ (optional).")
    parser.add_argument("--youtube", help="YouTube channel URL (optional).")
    parser.add_argument("--news-query", action="append", help="Extra Google News search query (repeatable).")
    parser.add_argument("--max-pages", type=int, help="Override max website pages to crawl.")
    parser.add_argument("--max-depth", type=int, help="Override max crawl depth.")
    parser.add_argument(
        "--skip",
        action="append",
        choices=["website", "instagram", "youtube", "news", "quiz", "embeddings"],
        help="Pipeline stage to skip (repeatable).",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    cfg = build_config_from_args(args)
    asyncio.run(run_pipeline(cfg))


if __name__ == "__main__":
    main()
