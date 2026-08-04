"""Heuristic HTML/text extraction used by the website scraper.

Every function is intentionally conservative (regex + keyword heuristics
rather than a heavyweight model) so it runs fast across hundreds of pages
without any GPU or paid API. Each extractor returns plain dicts that map
directly onto the `website.json` schema.
"""
from __future__ import annotations

import re
from typing import Dict, List

from bs4 import BeautifulSoup, Tag

YEAR_RE = re.compile(r"\b(1[89]\d{2}|20[0-4]\d)\b")

_KEYWORDS = {
    "milestones": ("milestone", "achieved", "became the first", "first to", "reached", "surpassed"),
    "statistics": ("percent", "%", "countries", "employees", "million", "billion", "market share", "revenue"),
    "awards": ("award", "recogni", "named ", "ranked", "won the", "honor", "prize"),
    "locations": ("headquartered", "headquarters", "based in", "offices in", "operates in", "presence in"),
    "partnerships": ("partner", "partnership", "collaborat", "alliance", "joint venture"),
    "acquisitions": ("acqui", "merger", "merged with", "divest"),
    "csr": ("sustainab", "corporate social responsibility", " csr ", "community", "diversity", "environment",
            "philanthrop", "carbon", "inclusion"),
}

_ROLE_KEYWORDS = (
    "chief executive officer", "ceo", "founder", "co-founder", "president",
    "chairman", "chairwoman", "chair of the board", "board member", "director",
    "chief financial officer", "cfo", "chief medical officer", "cmo",
    "chief scientific officer", "chief operating officer", "coo",
    "dermatologist", "spokesperson", "brand ambassador",
)


_BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "blockquote", "dt", "dd", "figcaption")


def _block_text(soup: BeautifulSoup) -> str:
    """Join block-level element text with sentence-ending punctuation so
    sentence splitting never glues an unrelated heading onto the next
    paragraph (which would otherwise corrupt every downstream regex
    extractor that operates on 'sentences')."""
    blocks = []
    for tag in soup.find_all(_BLOCK_TAGS):
        txt = tag.get_text(" ", strip=True)
        if not txt:
            continue
        if not txt.endswith((".", "!", "?", ":")):
            txt += "."
        blocks.append(txt)
    return " ".join(blocks)


def split_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)


def _sentences_matching(text: str, keywords) -> List[str]:
    out = []
    for sentence in split_sentences(text):
        low = sentence.lower()
        if any(kw in low for kw in keywords):
            if 15 <= len(sentence) <= 400:
                out.append(sentence.strip())
    return out


def extract_titles_and_headings(soup: BeautifulSoup) -> Dict[str, object]:
    title = soup.title.get_text(strip=True) if soup.title else ""
    headings = []
    for level in range(1, 5):
        for tag in soup.find_all(f"h{level}"):
            txt = tag.get_text(strip=True)
            if txt:
                headings.append({"level": level, "text": txt})
    return {"title": title, "headings": headings}


def extract_paragraphs(soup: BeautifulSoup) -> List[str]:
    paragraphs = []
    for tag in soup.find_all("p"):
        txt = tag.get_text(" ", strip=True)
        if len(txt) > 40:
            paragraphs.append(txt)
    return paragraphs


def extract_tables(soup: BeautifulSoup) -> List[List[List[str]]]:
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def extract_faqs(soup: BeautifulSoup) -> List[Dict[str, str]]:
    faqs = []
    # Pattern 1: dedicated faq containers
    candidates = soup.find_all(attrs={"class": re.compile("faq", re.I)})
    candidates += soup.find_all(attrs={"id": re.compile("faq", re.I)})
    for block in candidates:
        for q_tag in block.find_all(["h2", "h3", "h4", "dt", "summary"]):
            q_text = q_tag.get_text(" ", strip=True)
            if not q_text.endswith("?"):
                continue
            answer_tag = q_tag.find_next_sibling()
            a_text = answer_tag.get_text(" ", strip=True) if isinstance(answer_tag, Tag) else ""
            if q_text and a_text:
                faqs.append({"question": q_text, "answer": a_text})

    # Pattern 2: any heading ending in "?" followed by a paragraph anywhere on the page.
    for heading in soup.find_all(["h2", "h3", "h4"]):
        q_text = heading.get_text(" ", strip=True)
        if q_text.endswith("?"):
            nxt = heading.find_next_sibling("p")
            if nxt:
                faqs.append({"question": q_text, "answer": nxt.get_text(" ", strip=True)})

    # de-dupe by question text
    seen, unique = set(), []
    for f in faqs:
        if f["question"] not in seen:
            seen.add(f["question"])
            unique.append(f)
    return unique


def extract_timeline_mentions(text: str) -> List[Dict[str, object]]:
    """Find sentences that pair a 4-digit year with an event description."""
    events = []
    for sentence in split_sentences(text):
        years = YEAR_RE.findall(sentence)
        if years and 15 <= len(sentence) <= 300:
            for year in set(years):
                events.append({"year": int(year), "event": sentence.strip()})
    return events


_ROLE_WORDS = {w for phrase in _ROLE_KEYWORDS for w in phrase.split()}
_NAME_STOPWORDS = {
    "about", "our", "the", "leadership", "overview", "team", "management",
    "board", "company", "products", "portfolio", "milestones", "awards",
    "sustainability", "frequently", "asked", "questions", "home", "news",
}


def _looks_like_role_phrase(candidate: str) -> bool:
    """True if every word in the candidate is itself part of a role title
    (e.g. "Chief Financial Officer") rather than an actual person's name."""
    words = {w.lower() for w in candidate.split()}
    return words.issubset(_ROLE_WORDS) or bool(words & _NAME_STOPWORDS)


def extract_leadership_mentions(text: str) -> List[Dict[str, str]]:
    """Find 'Name, Role' or 'Role Name' style mentions near role keywords."""
    results = []
    name_pattern = re.compile(r"([A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+){1,3})")

    for sentence in split_sentences(text):
        low = sentence.lower()
        for role in _ROLE_KEYWORDS:
            if role in low:
                for match in name_pattern.finditer(sentence):
                    candidate = match.group(1).strip(" .,:;")
                    if not candidate or _looks_like_role_phrase(candidate) or len(candidate.split()) > 4:
                        continue
                    results.append({"name": candidate, "role": role, "context": sentence.strip()})
    return results


_NAME_DESC_SPLIT_RE = re.compile(r"\s+\b(?:is|are|was|were|offers|provides|helps|treats|delivers)\b")
_NAME_SEPARATORS = (" – ", " — ", " - ", ": ")


def _isolate_product_name(li_text: str) -> str:
    """List items are often full sentences ("Restylane is a leading dermal
    filler..."); keep just the leading name, not the whole description."""
    text = li_text
    for sep in _NAME_SEPARATORS:
        if sep in text:
            text = text.split(sep, 1)[0]
            break
    match = _NAME_DESC_SPLIT_RE.search(text)
    if match and match.start() >= 2:
        text = text[: match.start()]
    return text.strip()


def extract_products_mentions(soup: BeautifulSoup) -> List[str]:
    """Look for product lists under product/portfolio/brand-oriented sections."""
    products: List[str] = []
    trigger = re.compile(r"product|portfolio|brand|treatment|injectable|device", re.I)

    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        if not trigger.search(heading.get_text()):
            continue
        node = heading.find_next_sibling()
        hops = 0
        while node is not None and hops < 4:
            if isinstance(node, Tag) and node.name in ("ul", "ol"):
                for li in node.find_all("li"):
                    name = _isolate_product_name(li.get_text(" ", strip=True))
                    if 2 <= len(name) <= 60:
                        products.append(name)
                break
            if isinstance(node, Tag) and node.name and node.name.startswith("h"):
                break
            node = node.find_next_sibling() if isinstance(node, Tag) else None
            hops += 1

    return list(dict.fromkeys(products))  # dedupe, keep order


def extract_keyword_sections(text: str) -> Dict[str, List[str]]:
    """Run every keyword-bucket extractor (milestones, statistics, awards,
    locations, partnerships, acquisitions, csr) over the page text."""
    return {name: _sentences_matching(text, kws) for name, kws in _KEYWORDS.items()}


def parse_page(html: str, url: str) -> Dict[str, object]:
    """Top-level entry point: parse one HTML page into every category the
    spec asks for."""
    soup = BeautifulSoup(html, "lxml")

    # Strip script/style/nav noise before extracting free text.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    full_text = _block_text(soup)
    title_headings = extract_titles_and_headings(soup)

    return {
        "url": url,
        "title": title_headings["title"],
        "headings": title_headings["headings"],
        "paragraphs": extract_paragraphs(soup),
        "tables": extract_tables(soup),
        "faqs": extract_faqs(soup),
        "timeline_mentions": extract_timeline_mentions(full_text),
        "leadership_mentions": extract_leadership_mentions(full_text),
        "product_mentions": extract_products_mentions(soup),
        **extract_keyword_sections(full_text),
        "raw_text": full_text,
    }
