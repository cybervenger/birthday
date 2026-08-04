"""Builds `products.json` from product-name mentions collected by the
website scraper (and, opportunistically, from news headlines)."""
from __future__ import annotations

import re
from typing import Dict, List

from database.schema import Product
from parsers.content_parser import split_sentences
from utils.dedupe import dedupe_dicts

YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")

_CATEGORY_KEYWORDS = {
    "injectable aesthetics": ("filler", "injectable", "botox", "toxin", "neuromodulator", "dermal filler"),
    "prescription dermatology": ("prescription", "rx ", "topical", "biologic", "acne", "psoriasis", "eczema", "rosacea"),
    "dermocosmetics": ("dermocosmetic", "skincare", "moisturi", "sunscreen", "spf", "cleanser", "serum"),
    "aesthetic device": ("device", "laser", "energy-based", "machine"),
}

_INDICATION_KEYWORDS = {
    "wrinkles / anti-aging": ("wrinkle", "anti-aging", "fine line", "volumiz"),
    "acne": ("acne",),
    "psoriasis": ("psoriasis",),
    "atopic dermatitis / eczema": ("eczema", "atopic dermatitis"),
    "rosacea": ("rosacea",),
    "skin hydration / care": ("hydrat", "moistur", "sensitive skin"),
    "sun protection": ("spf", "sunscreen", "sun protection"),
}


def _guess(text: str, mapping: Dict[str, tuple]) -> str:
    low = text.lower()
    for label, kws in mapping.items():
        if any(kw in low for kw in kws):
            return label
    return "unknown"


def _find_launch_year(product_name: str, all_text: str) -> int | None:
    pattern = re.compile(
        rf"{re.escape(product_name)}[^.]{{0,80}}\b(launch|introduc|debut)[^.]{{0,40}}\b(19[5-9]\d|20[0-4]\d)\b",
        re.IGNORECASE,
    )
    match = pattern.search(all_text)
    if match:
        return int(match.group(2))
    return None


def build_products(company: str, website_pages: List[dict], news_items: List[dict]) -> List[dict]:
    """Turn raw `product_mentions` scraped from the website into structured
    Product records, using nearby text to guess category/indication/year."""
    all_text = " ".join(p.get("raw_text", "") for p in website_pages)

    seen_names: Dict[str, Product] = {}
    for page in website_pages:
        page_sentences = split_sentences(page.get("raw_text", ""))
        for name in page.get("product_mentions", []):
            clean = re.sub(r"\s+", " ", name).strip(" -•:")
            if not clean or len(clean) > 60 or clean.lower() in seen_names:
                continue
            # context = sentences on the same page that mention the product,
            # used to guess category/indication (avoids bleeding in unrelated
            # sections the way a raw character-offset window would).
            matching = [s for s in page_sentences if clean.lower() in s.lower()]
            window = " ".join(matching)[:400] if matching else clean

            product = Product(
                name=clean,
                category=_guess(window, _CATEGORY_KEYWORDS),
                indication=_guess(window, _INDICATION_KEYWORDS),
                launch_year=_find_launch_year(clean, all_text),
                brand=company,
                market="global",
                description=window.strip(),
                source=page.get("url", ""),
            )
            seen_names[clean.lower()] = product

    products = [p.__dict__ for p in seen_names.values()]
    return dedupe_dicts(products, "name")
