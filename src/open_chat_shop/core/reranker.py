"""RAG re-ranking (V2.0 module 2, feat-047).

A broad recall (Top-10) maximises the chance the answer is present; a lightweight
re-ranker then promotes the few most relevant documents (Top-3) before they are
fed to the LLM, cutting irrelevant context. The ``Reranker`` ABC lets a real
cross-encoder slot in later; ``TruncateReranker`` is the safe default that just
keeps the recall order, and ``LexicalReranker`` re-scores by character-bigram
overlap with the query.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from open_chat_shop.core.semantic_search import SearchResult


def _bigrams(text: str) -> set[str]:
    compact = text.replace(" ", "")
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


class Reranker(ABC):
    """Re-order recalled candidates and keep the most relevant *top_n*."""

    @abstractmethod
    def rerank(
        self, query: str, candidates: list[SearchResult], top_n: int = 3
    ) -> list[SearchResult]:
        """Return the *top_n* most relevant candidates for *query*."""


class TruncateReranker(Reranker):
    """Degradation default: keep the recall order and take the first *top_n*."""

    def rerank(
        self, query: str, candidates: list[SearchResult], top_n: int = 3
    ) -> list[SearchResult]:
        return list(candidates[:top_n])


class LexicalReranker(Reranker):
    """Lightweight reranker: re-score by char-bigram overlap with the query.

    A stable sort keeps the original recall order among ties, so this never
    does worse than recall when nothing overlaps.
    """

    def rerank(
        self, query: str, candidates: list[SearchResult], top_n: int = 3
    ) -> list[SearchResult]:
        query_grams = _bigrams(query)
        ranked = sorted(
            candidates,
            key=lambda c: len(query_grams & _bigrams(c.text)),
            reverse=True,
        )
        return ranked[:top_n]
