"""Embeds every fact in the knowledge base with sentence-transformers and
indexes the vectors with FAISS for fast semantic search.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, TypedDict

import numpy as np

from config import EmbeddingConfig, company_dir
from database.knowledge_base import KnowledgeBase
from utils.logging_config import get_logger

logger = get_logger(__name__)


class SearchHit(TypedDict):
    text: str
    source: str
    category: str
    score: float


class SemanticIndex:
    """Builds, persists, and queries a FAISS index over the company's facts."""

    def __init__(self, company: str, config: Optional[EmbeddingConfig] = None):
        self.company = company
        self.config = config or EmbeddingConfig()
        self.dir = company_dir(company) / "index"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "faiss.index"
        self.meta_path = self.dir / "meta.json"
        self._model = None
        self._index = None
        self._meta: List[dict] = []

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model '%s'...", self.config.model_name)
            self._model = SentenceTransformer(self.config.model_name)
        return self._model

    def _encode(self, texts: List[str]) -> np.ndarray:
        model = self._get_model()
        vectors = model.encode(texts, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True)
        return vectors.astype("float32")

    def build(self) -> int:
        """(Re)build the index from every fact/product/timeline/leader/news
        record currently stored in the knowledge base."""
        import faiss

        kb = KnowledgeBase(self.company)
        records = kb.all_fact_texts()
        records = [r for r in records if r["text"] and len(r["text"].strip()) > 5]

        if not records:
            logger.warning("No records to embed for '%s' — index not built.", self.company)
            return 0

        texts = [r["text"] for r in records]
        vectors = self._encode(texts)

        dim = vectors.shape[1]
        index = faiss.IndexFlatIP(dim)  # cosine similarity via normalized vectors
        index.add(vectors)

        faiss.write_index(index, str(self.index_path))
        self.meta_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

        self._index = index
        self._meta = records
        logger.info("Built FAISS index for '%s' with %d vectors.", self.company, len(records))
        return len(records)

    def _load(self) -> bool:
        if self._index is not None:
            return True
        if not self.index_path.exists() or not self.meta_path.exists():
            return False
        import faiss

        self._index = faiss.read_index(str(self.index_path))
        self._meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        return True

    def search(self, query: str, top_k: Optional[int] = None) -> List[SearchHit]:
        if not self._load():
            logger.warning("No index found for '%s'. Run build() first.", self.company)
            return []

        k = top_k or self.config.top_k
        query_vec = self._encode([query])
        scores, idxs = self._index.search(query_vec, min(k, len(self._meta)))

        hits: List[SearchHit] = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx == -1:
                continue
            record = self._meta[idx]
            hits.append(SearchHit(text=record["text"], source=record["source"], category=record.get("category", "general"), score=float(score)))
        return hits
