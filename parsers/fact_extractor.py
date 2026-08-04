"""Lightweight NLP fact extraction.

Turns raw scraped text into a flat list of atomic, citable factual
statements ("Galderma operates in over 100 countries.") grouped by
category. Uses spaCy for named-entity confidence boosting when the
`en_core_web_sm` model is available, and falls back to pure regex/keyword
heuristics when it isn't (spaCy models are a large optional download and
the pipeline must keep working without them).
"""
from __future__ import annotations

import re
from typing import List, Optional

from database.schema import Fact
from utils.dedupe import dedupe_dicts

_FACT_SIGNAL_RE = re.compile(
    r"\b(founded|established|headquartered|operates? in|over \d|more than \d|"
    r"focuses? on|specializ|is a |is the |provides|offers|serves|employs|"
    r"present in|available in)\b",
    re.IGNORECASE,
)
_HAS_NUMBER_RE = re.compile(r"\d")

_CATEGORY_RULES = [
    ("founding", ("founded", "established", "incorporated", "spun off", "spin-off")),
    ("scale", ("countries", "employees", "million", "billion", "market share", "revenue", "offices")),
    ("focus", ("focuses on", "specializ", "dedicated to", "mission", "pure-play", "dermatology")),
    ("products", ("product", "portfolio", "brand", "injectable", "skincare", "treatment")),
    ("leadership", ("ceo", "chief executive", "founder", "president", "chairman", "board")),
    ("csr", ("sustainab", "csr", "community", "diversity", "philanthrop", "environment")),
    ("awards", ("award", "recogni", "ranked", "named ", "won the")),
    ("acquisitions", ("acqui", "merger", "divest")),
    ("partnerships", ("partner", "collaborat", "alliance")),
]

_nlp = None
_SPACY_TRIED = False


def _get_spacy():
    """Lazily load spaCy's small English model; return None if unavailable."""
    global _nlp, _SPACY_TRIED
    if _SPACY_TRIED:
        return _nlp
    _SPACY_TRIED = True
    try:
        import spacy

        _nlp = spacy.load("en_core_web_sm")
    except Exception:  # noqa: BLE001 - model not installed / spaCy missing
        _nlp = None
    return _nlp


def _categorize(sentence: str) -> str:
    low = sentence.lower()
    for category, keywords in _CATEGORY_RULES:
        if any(kw in low for kw in keywords):
            return category
    return "general"


def _confidence(sentence: str, nlp) -> float:
    score = 0.55
    if _HAS_NUMBER_RE.search(sentence):
        score += 0.2
    if nlp is not None:
        doc = nlp(sentence)
        if any(ent.label_ in ("ORG", "GPE", "DATE", "PERCENT", "CARDINAL", "MONEY") for ent in doc.ents):
            score += 0.15
    return min(round(score, 2), 0.95)


def _split_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    return re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text) if text else []


def extract_facts_from_text(text: str, source: str) -> List[Fact]:
    """Extract candidate factual sentences from a single block of text."""
    nlp = _get_spacy()
    facts: List[Fact] = []
    for sentence in _split_sentences(text):
        sentence = sentence.strip()
        if not (20 <= len(sentence) <= 280):
            continue
        if not _FACT_SIGNAL_RE.search(sentence):
            continue
        facts.append(
            Fact(
                text=sentence,
                source=source,
                category=_categorize(sentence),
                confidence=_confidence(sentence, nlp),
            )
        )
    return facts


def build_facts(
    website_pages: List[dict],
    news_items: List[dict],
    products: List[dict],
    leaders: List[dict],
    timeline: List[dict],
) -> List[dict]:
    """Run fact extraction over every collected data source and merge the
    results into a single de-duplicated facts list."""
    facts: List[Fact] = []

    for page in website_pages:
        source = page.get("url", "website")
        facts.extend(extract_facts_from_text(page.get("raw_text", ""), source))
        # Keyword-bucketed sentences are already high-signal; keep them directly.
        for category in ("statistics", "awards", "locations", "partnerships", "acquisitions", "csr", "milestones"):
            for sentence in page.get(category, []):
                facts.append(Fact(text=sentence, source=source, category=category, confidence=0.75))

    for item in news_items:
        text = f"{item.get('headline', '')}. {item.get('summary', '')}"
        facts.extend(extract_facts_from_text(text, item.get("url", "news")))

    for t in timeline:
        facts.append(
            Fact(
                text=f"{t['year']}: {t['event']}",
                source=t.get("source", "timeline"),
                category="founding" if t.get("importance") == "high" else "general",
                confidence=0.8,
            )
        )

    for p in products:
        desc = f"{p['name']} is a {p.get('category', 'product')} product" \
               f"{' for ' + p['indication'] if p.get('indication') and p['indication'] != 'unknown' else ''}."
        facts.append(Fact(text=desc, source=p.get("source", "products"), category="products", confidence=0.7))

    for l in leaders:
        facts.append(
            Fact(
                text=f"{l['name']} serves as {l['role']}.",
                source=l.get("source", "leaders"),
                category="leadership",
                confidence=0.75,
            )
        )

    fact_dicts = [f.__dict__ for f in facts]
    return dedupe_dicts(fact_dicts, "text")
