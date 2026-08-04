"""Typed data structures shared across the whole pipeline.

Every scraper/parser produces lists of these dataclasses; `KnowledgeBase`
serializes them to the JSON files listed in the project spec
(facts.json, products.json, timeline.json, ...).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Fact:
    text: str
    source: str  # e.g. "website:/about", "news:<url>", "instagram:<shortcode>"
    category: str = "general"  # founding, scale, products, leadership, csr, awards...
    confidence: float = 0.8


@dataclass
class Product:
    name: str
    category: str = "unknown"
    indication: str = "unknown"
    launch_year: Optional[int] = None
    brand: str = "unknown"
    market: str = "unknown"
    description: str = ""
    source: str = ""


@dataclass
class TimelineEvent:
    year: int
    event: str
    importance: str = "medium"  # low / medium / high
    source: str = ""


@dataclass
class Leader:
    name: str
    role: str  # CEO, Founder, Executive, Board Member, Dermatologist, Spokesperson
    bio: str = ""
    source: str = ""


@dataclass
class NewsItem:
    headline: str
    summary: str
    publication: str
    date: str
    url: str
    query: str = ""


@dataclass
class InstagramPost:
    shortcode: str
    caption: str
    hashtags: List[str] = field(default_factory=list)
    date: str = ""
    likes: Optional[int] = None
    comments_count: Optional[int] = None
    is_video: bool = False
    alt_text: str = ""
    image_path: str = ""
    url: str = ""


@dataclass
class YouTubeVideo:
    video_id: str
    title: str
    description: str
    upload_date: str
    view_count: Optional[int] = None
    comment_count: Optional[int] = None
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    transcript_path: str = ""
    url: str = ""


@dataclass
class QuizQuestion:
    question: str
    answer: str
    difficulty: str  # easy / medium / hard / very_hard
    q_type: str  # mcq / true_false / fill_blank / one_word
    options: List[str] = field(default_factory=list)
    source: str = ""


def to_dict(obj: Any) -> Dict[str, Any]:
    return asdict(obj)


def list_to_dicts(items: List[Any]) -> List[Dict[str, Any]]:
    return [asdict(i) for i in items]
