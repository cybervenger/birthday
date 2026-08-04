"""Simple text de-duplication helpers shared by parsers and extractors."""
from __future__ import annotations

import hashlib
import re
from typing import Iterable, List

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapse whitespace and lowercase for hashing/comparison purposes."""
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def dedupe_strings(items: Iterable[str], min_len: int = 0) -> List[str]:
    """Return items with duplicate/near-duplicate (normalized) text removed."""
    seen: set = set()
    out: List[str] = []
    for item in items:
        if not item or len(item.strip()) < min_len:
            continue
        h = text_hash(item)
        if h in seen:
            continue
        seen.add(h)
        out.append(item.strip())
    return out


def dedupe_dicts(items: Iterable[dict], key_field: str) -> List[dict]:
    seen: set = set()
    out: List[dict] = []
    for item in items:
        key = text_hash(str(item.get(key_field, "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
