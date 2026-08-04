"""Generates multiple-choice, true/false, fill-in-the-blank and one-word
quiz questions across four difficulty tiers from the scraped knowledge base.
"""
from __future__ import annotations

import random
import re
from typing import Dict, List, Optional

from config import QuizConfig
from database.schema import QuizQuestion

_NUMBER_RE = re.compile(r"\b\d[\d,]*\+?\b")
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*)\b")


def _rng(seed: Optional[int] = None) -> random.Random:
    return random.Random(seed)


def _distractors(pool: List[str], correct: str, n: int, rng: random.Random) -> List[str]:
    candidates = [p for p in pool if p and p.strip().lower() != correct.strip().lower()]
    rng.shuffle(candidates)
    picked = []
    for c in candidates:
        if c not in picked:
            picked.append(c)
        if len(picked) == n:
            break
    return picked


def _mcq(question: str, correct: str, distractors: List[str], difficulty: str, source: str, rng: random.Random) -> QuizQuestion:
    options = list(dict.fromkeys([correct, *distractors]))
    rng.shuffle(options)
    return QuizQuestion(question=question, answer=correct, difficulty=difficulty, q_type="mcq", options=options, source=source)


def _true_false(statement: str, is_true: bool, difficulty: str, source: str) -> QuizQuestion:
    return QuizQuestion(
        question=f"True or False: {statement}",
        answer="True" if is_true else "False",
        difficulty=difficulty,
        q_type="true_false",
        options=["True", "False"],
        source=source,
    )


def _fill_blank(sentence: str, blank: str, difficulty: str, source: str) -> Optional[QuizQuestion]:
    if blank not in sentence:
        return None
    masked = sentence.replace(blank, "______", 1)
    return QuizQuestion(question=masked, answer=blank, difficulty=difficulty, q_type="fill_blank", source=source)


def _one_word(question: str, answer: str, difficulty: str, source: str) -> QuizQuestion:
    return QuizQuestion(question=question, answer=answer, difficulty=difficulty, q_type="one_word", source=source)


def _pick_blank_token(sentence: str) -> Optional[str]:
    """Pick the most 'informative' token to blank out: prefer a year, then a
    number, then the longest proper-noun phrase."""
    year = _YEAR_RE.search(sentence)
    if year:
        return year.group(0)
    number = _NUMBER_RE.search(sentence)
    if number:
        return number.group(0)
    nouns = _PROPER_NOUN_RE.findall(sentence)
    nouns = [n for n in nouns if len(n) > 3]
    if nouns:
        return max(nouns, key=len)
    return None


def _falsify_number(sentence: str, rng: random.Random) -> Optional[str]:
    """Produce a plausible-but-wrong variant of a fact by nudging a
    year/number, for true/false questions."""
    year_match = _YEAR_RE.search(sentence)
    if year_match:
        year = int(year_match.group(0))
        wrong = year + rng.choice([-15, -10, -7, 7, 10, 15])
        return sentence[: year_match.start()] + str(wrong) + sentence[year_match.end():]

    num_match = _NUMBER_RE.search(sentence)
    if num_match:
        raw = num_match.group(0).rstrip("+").replace(",", "")
        if raw.isdigit():
            wrong = int(raw) + rng.choice([-20, -10, 10, 20, 30])
            wrong = max(wrong, 1)
            return sentence[: num_match.start()] + str(wrong) + sentence[num_match.end():]
    return None


def _leadership_questions(company: str, leaders: List[dict], difficulty: str, rng: random.Random) -> List[QuizQuestion]:
    out: List[QuizQuestion] = []
    names = [l["name"] for l in leaders]
    for leader in leaders:
        distractors = _distractors(names, leader["name"], 3, rng)
        if len(distractors) < 2:
            continue
        q = f"Who currently serves as {company}'s {leader['role']}?"
        out.append(_mcq(q, leader["name"], distractors, difficulty, leader.get("source", ""), rng))
        out.append(_one_word(f"Name the {leader['role']} of {company}.", leader["name"], difficulty, leader.get("source", "")))
    return out


def _timeline_questions(company: str, timeline: List[dict], difficulty: str, rng: random.Random) -> List[QuizQuestion]:
    out: List[QuizQuestion] = []
    years = [str(t["year"]) for t in timeline]
    for event in timeline:
        year = str(event["year"])
        distractors = _distractors(years, year, 3, rng)
        if len(distractors) < 2:
            continue
        q = f"In which year did this happen: \"{event['event']}\"?"
        out.append(_mcq(q, year, distractors, difficulty, event.get("source", ""), rng))
        fb = _fill_blank(event["event"], year, difficulty, event.get("source", ""))
        if fb:
            out.append(fb)
    return out


def _product_questions(company: str, products: List[dict], difficulty: str, rng: random.Random) -> List[QuizQuestion]:
    out: List[QuizQuestion] = []
    names = [p["name"] for p in products]
    categories = list({p["category"] for p in products if p.get("category") and p["category"] != "unknown"})

    for product in products:
        distractors = _distractors(names, product["name"], 3, rng)
        if len(distractors) >= 2:
            q = f"Which of the following belongs to {company}'s product portfolio?"
            out.append(_mcq(q, product["name"], distractors, difficulty, product.get("source", ""), rng))

        if product.get("category") and product["category"] != "unknown":
            cat_distractors = _distractors(categories, product["category"], 3, rng)
            if len(cat_distractors) >= 2:
                q = f"Which category does the product \"{product['name']}\" belong to?"
                out.append(_mcq(q, product["category"], cat_distractors, difficulty, product.get("source", ""), rng))
    return out


def _fact_questions(company: str, facts: List[dict], difficulty: str, rng: random.Random) -> List[QuizQuestion]:
    out: List[QuizQuestion] = []
    for fact in facts:
        sentence = fact["text"]
        blank = _pick_blank_token(sentence)
        if blank:
            fb = _fill_blank(sentence, blank, difficulty, fact.get("source", ""))
            if fb:
                out.append(fb)

        if rng.random() < 0.5:
            out.append(_true_false(sentence, True, difficulty, fact.get("source", "")))
        else:
            wrong = _falsify_number(sentence, rng)
            if wrong:
                out.append(_true_false(wrong, False, difficulty, fact.get("source", "")))
            else:
                out.append(_true_false(sentence, True, difficulty, fact.get("source", "")))
    return out


def _difficulty_for_fact(fact: dict) -> str:
    conf = fact.get("confidence", 0.7)
    category = fact.get("category", "general")
    if category in ("founding", "leadership") and conf >= 0.75:
        return "easy"
    if category in ("scale", "products", "focus"):
        return "medium"
    if category in ("acquisitions", "partnerships", "awards"):
        return "hard"
    return "very_hard" if conf < 0.65 else "hard"


def generate_quiz(
    company: str,
    facts: List[dict],
    products: List[dict],
    timeline: List[dict],
    leaders: List[dict],
    config: Optional[QuizConfig] = None,
    seed: Optional[int] = 42,
) -> List[dict]:
    """Generate the full quiz bank and trim each difficulty bucket down to
    the configured question count."""
    cfg = config or QuizConfig()
    rng = _rng(seed)

    buckets: Dict[str, List[QuizQuestion]] = {"easy": [], "medium": [], "hard": [], "very_hard": []}

    buckets["easy"].extend(_leadership_questions(company, [l for l in leaders if l["role"] == "CEO"], "easy", rng))
    buckets["medium"].extend(_leadership_questions(company, [l for l in leaders if l["role"] != "CEO"], "medium", rng))

    founding_events = [t for t in timeline if t.get("importance") == "high"]
    buckets["easy"].extend(_timeline_questions(company, founding_events, "easy", rng))
    other_events = [t for t in timeline if t.get("importance") != "high"]
    buckets["hard"].extend(_timeline_questions(company, other_events, "hard", rng))

    buckets["medium"].extend(_product_questions(company, products, "medium", rng))
    buckets["hard"].extend(_product_questions(company, products, "hard", rng))

    for fact in facts:
        difficulty = _difficulty_for_fact(fact)
        buckets[difficulty].extend(_fact_questions(company, [fact], difficulty, rng))

    targets = {
        "easy": cfg.easy_count,
        "medium": cfg.medium_count,
        "hard": cfg.hard_count,
        "very_hard": cfg.very_hard_count,
    }

    final: List[dict] = []
    for difficulty, target in targets.items():
        pool = buckets[difficulty]
        rng.shuffle(pool)
        # Keep a mix of question types rather than N copies of the same type.
        by_type: Dict[str, List[QuizQuestion]] = {}
        for q in pool:
            by_type.setdefault(q.q_type, []).append(q)
        selected: List[QuizQuestion] = []
        type_cycle = list(by_type.keys())
        i = 0
        while len(selected) < target and any(by_type.values()):
            t = type_cycle[i % len(type_cycle)]
            if by_type.get(t):
                selected.append(by_type[t].pop())
            i += 1
            if i > target * 10:
                break
        final.extend(q.__dict__ for q in selected)

    return final
