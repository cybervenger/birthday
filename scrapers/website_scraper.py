"""Async crawler for the company's official website.

Breadth-first crawl restricted to the seed domain, robots.txt aware,
checkpointed so an interrupted run can resume without re-fetching pages.
Falls back to a headless Playwright render for pages that come back
suspiciously thin over plain HTTP (a strong signal of a JS-only page).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional, Set
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup
from slugify import slugify

from config import CrawlConfig, company_dir
from parsers.content_parser import parse_page
from utils.checkpoint import Checkpoint
from utils.http_client import AsyncHTTPClient
from utils.logging_config import get_logger
from utils.robots import RobotsChecker

logger = get_logger(__name__)

_SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".mp4", ".mp3",
    ".doc", ".docx", ".xls", ".xlsx", ".css", ".js", ".ico", ".webp",
)


@dataclass
class CrawlResult:
    pages: List[dict]


def _same_domain(seed_netloc: str, candidate: str) -> bool:
    netloc = urlparse(candidate).netloc.lower()
    seed = seed_netloc.lower().removeprefix("www.")
    return netloc.removeprefix("www.") == seed


def _normalize_link(base_url: str, href: str) -> Optional[str]:
    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
        return None
    joined = urljoin(base_url, href)
    joined, _ = urldefrag(joined)
    if any(joined.lower().endswith(ext) for ext in _SKIP_EXTENSIONS):
        return None
    return joined


async def _render_with_playwright(url: str, timeout: float) -> Optional[str]:
    """Best-effort headless render for JS-heavy pages. Returns None on any failure
    so the caller can gracefully keep the plain-HTTP content instead."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            html = await page.content()
            await browser.close()
            return html
    except Exception as exc:  # noqa: BLE001
        logger.info("Playwright render failed for %s: %s", url, exc)
        return None


def _to_markdown(parsed: dict) -> str:
    lines = [f"# {parsed['title'] or parsed['url']}", "", f"Source: {parsed['url']}", ""]
    for h in parsed["headings"]:
        lines.append(f"{'#' * min(h['level'] + 1, 6)} {h['text']}")
    lines.append("")
    for p in parsed["paragraphs"]:
        lines.append(p)
        lines.append("")
    if parsed["tables"]:
        lines.append("## Tables")
        for table in parsed["tables"]:
            for row in table:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")
    if parsed["faqs"]:
        lines.append("## FAQs")
        for faq in parsed["faqs"]:
            lines.append(f"**Q: {faq['question']}**")
            lines.append(f"A: {faq['answer']}")
            lines.append("")
    return "\n".join(lines)


class WebsiteScraper:
    def __init__(self, company: str, seed_url: str, config: Optional[CrawlConfig] = None):
        self.company = company
        self.seed_url = seed_url
        self.config = config or CrawlConfig()
        self.seed_netloc = urlparse(seed_url).netloc
        self.out_dir = company_dir(company)
        self.md_dir = self.out_dir / "website_markdown"
        self.md_dir.mkdir(exist_ok=True)
        self.checkpoint = Checkpoint(company, "website")
        self.robots = RobotsChecker(seed_url, self.config.user_agent, self.config.respect_robots_txt)

    async def crawl(self) -> List[dict]:
        await self.robots.load()

        results: List[dict] = self.checkpoint.get_state("results", [])
        visited: Set[str] = self.checkpoint.done
        queue: List[tuple[str, int]] = [(self.seed_url, 0)]
        queued: Set[str] = {self.seed_url}
        semaphore = asyncio.Semaphore(self.config.concurrency)

        async with AsyncHTTPClient(
            timeout=self.config.request_timeout,
            retries=self.config.retries,
            rate_limit_delay=self.config.rate_limit_delay,
        ) as client:

            while queue and len(visited) < self.config.max_pages:
                batch = queue[: self.config.concurrency]
                queue = queue[self.config.concurrency:]

                async def process(url: str, depth: int):
                    if url in visited or not self.robots.can_fetch(url):
                        return []
                    async with semaphore:
                        return await self._fetch_and_parse(client, url, depth, results)

                tasks = [process(u, d) for u, d in batch if u not in visited]
                batches_of_links = await asyncio.gather(*tasks)

                for (url, depth), links in zip(batch, batches_of_links):
                    visited.add(url)
                    self.checkpoint.mark_done(url)
                    if depth < self.config.max_depth:
                        for link in links:
                            if link not in queued and link not in visited:
                                queue.append((link, depth + 1))
                                queued.add(link)

                self.checkpoint.set_state("results", results)

        logger.info("Website crawl complete: %d pages fetched from %s", len(results), self.seed_url)
        return results

    async def _fetch_and_parse(self, client: AsyncHTTPClient, url: str, depth: int, results: List[dict]) -> List[str]:
        resp = await client.get(url)
        if resp is None:
            return []
        html = resp.text
        if len(BeautifulSoup(html, "lxml").get_text(strip=True)) < 200:
            rendered = await _render_with_playwright(url, self.config.request_timeout)
            if rendered:
                html = rendered

        parsed = parse_page(html, url)
        results.append(parsed)

        md_path = self.md_dir / f"{slugify(url)[:120]}.md"
        md_path.write_text(_to_markdown(parsed), encoding="utf-8")

        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            normalized = _normalize_link(url, a["href"])
            if normalized and _same_domain(self.seed_netloc, normalized):
                links.append(normalized)
        return links


async def scrape_website(company: str, seed_url: str, config: Optional[CrawlConfig] = None) -> List[dict]:
    scraper = WebsiteScraper(company, seed_url, config)
    return await scraper.crawl()
