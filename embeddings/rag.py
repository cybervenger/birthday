"""Local, citation-only Retrieval-Augmented Generation.

By default this performs pure extractive synthesis: it retrieves the most
relevant facts from the FAISS index and stitches them into an answer built
*only* from that retrieved text, each sentence tagged with its source. This
guarantees no hallucination since nothing is generated outside the scraped
corpus.

If an Anthropic API key is present in the environment, `synthesize_with_llm`
can optionally be used to phrase a more fluent answer — but it is
instructed to use only the supplied context and is never called unless the
caller explicitly opts in.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from embeddings.embedder import SearchHit, SemanticIndex
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class RAGAnswer:
    question: str
    answer: str
    citations: List[str]
    hits: List[SearchHit]


def _extractive_answer(question: str, hits: List[SearchHit]) -> str:
    if not hits:
        return "No relevant information was found in the scraped knowledge base for this question."
    lines = []
    for i, hit in enumerate(hits, start=1):
        lines.append(f"{i}. {hit['text']} [source: {hit['source']}]")
    return "Based on the scraped knowledge base:\n" + "\n".join(lines)


def synthesize_with_llm(question: str, hits: List[SearchHit]) -> Optional[str]:
    """Optional fluent synthesis via the Anthropic API, strictly grounded in
    the retrieved context. Returns None if no API key is configured or the
    call fails, so callers should always fall back to `_extractive_answer`.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic

        context = "\n".join(f"- {h['text']} (source: {h['source']})" for h in hits)
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=400,
            system=(
                "Answer using ONLY the provided context. If the context does not contain "
                "the answer, say so explicitly. Always cite the source in brackets after "
                "each claim, e.g. [source: ...]. Never invent facts not present in the context."
            ),
            messages=[{"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}],
        )
        return response.content[0].text
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM synthesis unavailable, falling back to extractive answer: %s", exc)
        return None


class LocalRAG:
    """Retrieval-augmented question answering scoped to a single company's
    scraped knowledge base."""

    def __init__(self, company: str, top_k: int = 5, use_llm: bool = False):
        self.company = company
        self.top_k = top_k
        self.use_llm = use_llm
        self.index = SemanticIndex(company)

    def ask(self, question: str) -> RAGAnswer:
        hits = self.index.search(question, top_k=self.top_k)

        answer = None
        if self.use_llm:
            answer = synthesize_with_llm(question, hits)
        if answer is None:
            answer = _extractive_answer(question, hits)

        citations = list(dict.fromkeys(h["source"] for h in hits))
        return RAGAnswer(question=question, answer=answer, citations=citations, hits=hits)
