"""Persistence layer for the trivia knowledge base.

Wraps the per-company `data/<slug>/` directory and knows how to read/write
every JSON artifact described in the project spec:
facts.json, products.json, timeline.json, leaders.json, news.json,
instagram.json, youtube.json, website.json, quiz.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from config import company_dir
from utils.dedupe import dedupe_dicts
from utils.logging_config import get_logger

logger = get_logger(__name__)

_FILES = {
    "website": "website.json",
    "website_full": "website_full_internal.json",
    "instagram": "instagram.json",
    "youtube": "youtube.json",
    "news": "news.json",
    "products": "products.json",
    "timeline": "timeline.json",
    "leaders": "leaders.json",
    "facts": "facts.json",
    "quiz": "quiz.json",
}

_DEDUPE_KEY = {
    "news": "url",
    "website": "url",
    "website_full": "url",
    "products": "name",
    "leaders": "name",
    "facts": "text",
    "instagram": "shortcode",
    "youtube": "video_id",
}


class KnowledgeBase:
    """Read/write access to a single company's knowledge base on disk."""

    def __init__(self, company: str):
        self.company = company
        self.dir: Path = company_dir(company)

    def path_for(self, key: str) -> Path:
        if key not in _FILES:
            raise KeyError(f"Unknown knowledge-base file: {key}")
        return self.dir / _FILES[key]

    def save(self, key: str, data: Any) -> None:
        path = self.path_for(key)
        if isinstance(data, list) and key in _DEDUPE_KEY:
            data = dedupe_dicts(data, _DEDUPE_KEY[key])
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        count = len(data) if isinstance(data, list) else 1
        logger.info("Saved %s (%d records) -> %s", key, count, path)

    def load(self, key: str, default: Any = None) -> Any:
        path = self.path_for(key)
        if not path.exists():
            return default if default is not None else []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Corrupt JSON for %s, returning empty.", key)
            return default if default is not None else []

    def append(self, key: str, records: List[Dict[str, Any]]) -> None:
        existing = self.load(key, default=[])
        existing.extend(records)
        self.save(key, existing)

    def summary(self) -> Dict[str, int]:
        out = {}
        for key in _FILES:
            data = self.load(key, default=[])
            out[key] = len(data) if isinstance(data, list) else (1 if data else 0)
        return out

    def all_fact_texts(self) -> List[Dict[str, str]]:
        """Flatten every fact-like record across the KB into (text, source) pairs
        for embedding — used by the semantic search / RAG layer."""
        pairs: List[Dict[str, str]] = []

        for f in self.load("facts", default=[]):
            pairs.append({"text": f["text"], "source": f.get("source", "facts"), "category": f.get("category", "general")})

        for p in self.load("products", default=[]):
            desc = f"{p['name']} is a {p.get('category', 'product')} " \
                   f"({p.get('indication', 'unknown indication')}), brand: {p.get('brand', 'unknown')}. " \
                   f"{p.get('description', '')}".strip()
            pairs.append({"text": desc, "source": p.get("source", "products"), "category": "product"})

        for t in self.load("timeline", default=[]):
            pairs.append({"text": f"{t['year']}: {t['event']}", "source": t.get("source", "timeline"), "category": "timeline"})

        for l in self.load("leaders", default=[]):
            bio = f" {l.get('bio', '')}".rstrip()
            pairs.append({"text": f"{l['name']} is the {l['role']} of the company.{bio}", "source": l.get("source", "leaders"), "category": "leadership"})

        for n in self.load("news", default=[]):
            pairs.append({"text": f"{n['headline']} — {n.get('summary', '')}".strip(" —"), "source": n.get("url", "news"), "category": "news"})

        return pairs
