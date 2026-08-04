"""Builds `leaders.json` from leadership mentions scraped off the website."""
from __future__ import annotations

from typing import Dict, List

from database.schema import Leader

_ROLE_CANONICAL = {
    "chief executive officer": "CEO",
    "ceo": "CEO",
    "founder": "Founder",
    "co-founder": "Founder",
    "president": "President",
    "chairman": "Chairman",
    "chairwoman": "Chairwoman",
    "chair of the board": "Board Chair",
    "board member": "Board Member",
    "director": "Director",
    "chief financial officer": "CFO",
    "cfo": "CFO",
    "chief medical officer": "CMO",
    "cmo": "CMO",
    "chief scientific officer": "Chief Scientific Officer",
    "chief operating officer": "COO",
    "coo": "COO",
    "dermatologist": "Dermatologist",
    "spokesperson": "Spokesperson",
    "brand ambassador": "Spokesperson",
}

# Roughly reflects seniority for ordering the leadership table in the dashboard.
_ROLE_RANK = {
    "CEO": 0, "Founder": 1, "President": 2, "Chairman": 3, "Chairwoman": 3,
    "Board Chair": 3, "CFO": 4, "COO": 4, "CMO": 4, "Chief Scientific Officer": 4,
    "Board Member": 5, "Director": 6, "Dermatologist": 7, "Spokesperson": 8,
}


def build_leaders(website_pages: List[dict]) -> List[dict]:
    """De-duplicate leadership mentions by (name, canonical role) and keep the
    longest surrounding sentence found as a short bio."""
    best: Dict[tuple, Leader] = {}

    for page in website_pages:
        for mention in page.get("leadership_mentions", []):
            role = _ROLE_CANONICAL.get(mention["role"].lower(), mention["role"].title())
            key = (mention["name"].strip().lower(), role)
            context = mention.get("context", "")

            if key not in best or len(context) > len(best[key].bio):
                best[key] = Leader(
                    name=mention["name"].strip(),
                    role=role,
                    bio=context.strip(),
                    source=page.get("url", ""),
                )

    leaders = list(best.values())
    leaders.sort(key=lambda l: _ROLE_RANK.get(l.role, 9))
    return [l.__dict__ for l in leaders]
