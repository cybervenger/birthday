"""Central configuration for the Company Trivia Intelligence System.

Every module reads its paths, limits, and tunables from here so behaviour can
be changed in one place instead of hunting through the codebase.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------- #
# Filesystem layout
# --------------------------------------------------------------------------- #
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
CHECKPOINT_DIR = ROOT_DIR / "checkpoints"

for _d in (DATA_DIR, LOG_DIR, CHECKPOINT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def company_dir(company: str) -> Path:
    """Return (and create) the per-company data directory."""
    from slugify import slugify

    path = DATA_DIR / slugify(company)
    (path / "images").mkdir(parents=True, exist_ok=True)
    (path / "transcripts").mkdir(parents=True, exist_ok=True)
    (path / "index").mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------- #
# Networking / crawl behaviour
# --------------------------------------------------------------------------- #
@dataclass
class CrawlConfig:
    max_pages: int = 120
    max_depth: int = 4
    concurrency: int = 5
    request_timeout: float = 20.0
    retries: int = 3
    backoff_base: float = 1.5
    rate_limit_delay: float = 0.6  # polite delay between requests to the same host
    respect_robots_txt: bool = True
    user_agent: str = (
        "Mozilla/5.0 (compatible; CompanyTriviaBot/1.0; "
        "+https://github.com/cybervenger/birthday; educational-research)"
    )


@dataclass
class InstagramConfig:
    max_posts: int = 60
    download_images: bool = True
    login_username: Optional[str] = field(default_factory=lambda: os.getenv("IG_USERNAME"))
    login_password: Optional[str] = field(default_factory=lambda: os.getenv("IG_PASSWORD"))


@dataclass
class YouTubeConfig:
    max_videos: int = 40
    download_transcripts: bool = True
    languages: tuple = ("en",)


@dataclass
class NewsConfig:
    max_articles_per_query: int = 25
    language: str = "en-US"
    country: str = "US"


@dataclass
class EmbeddingConfig:
    model_name: str = "all-MiniLM-L6-v2"
    index_type: str = "flat"  # "flat" or "ivf"
    top_k: int = 5


@dataclass
class QuizConfig:
    easy_count: int = 10
    medium_count: int = 10
    hard_count: int = 8
    very_hard_count: int = 6


@dataclass
class PipelineConfig:
    """Top-level configuration bundle produced from CLI arguments."""

    company: str
    website: Optional[str] = None
    instagram_handle: Optional[str] = None
    youtube_channel: Optional[str] = None
    news_queries: list = field(default_factory=list)
    skip: set = field(default_factory=set)  # stage names to skip
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    instagram: InstagramConfig = field(default_factory=InstagramConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    quiz: QuizConfig = field(default_factory=QuizConfig)

    def __post_init__(self) -> None:
        if not self.news_queries:
            self.news_queries = [
                self.company,
                f"{self.company} products",
                f"{self.company} acquisitions",
                f"{self.company} CEO",
                f"{self.company} awards",
                f"{self.company} expansion",
                f"{self.company} launches",
            ]

    @property
    def out_dir(self) -> Path:
        return company_dir(self.company)


# Default request headers shared across scrapers
DEFAULT_HEADERS = {
    "User-Agent": CrawlConfig.user_agent,
    "Accept-Language": "en-US,en;q=0.9",
}
