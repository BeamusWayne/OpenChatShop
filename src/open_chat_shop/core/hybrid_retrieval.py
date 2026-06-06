"""Hybrid RAG retrieval (V2.0 module 2, feat-046).

Structured queries — those a structured intent matched — keep going through
Function Calling against the live commerce data. An unstructured query (one no
structured intent matched, i.e. ``fallback``: "这款会缩水吗", "退货政策是什么")
is routed instead to semantic retrieval over a FAQ / product knowledge base
built on the feat-044 VectorStore.

This module provides the retrieval half (ingest + retrieve) and the routing
decision. Wiring it into the dialogue flow is a deployment concern, kept out of
the core path so the structured behaviour is unchanged.
"""
from __future__ import annotations

from open_chat_shop.core.reranker import Reranker
from open_chat_shop.core.semantic_search import (
    EmbeddingService,
    SearchResult,
    VectorStore,
)
from open_chat_shop.core.types import Intent


def should_use_rag(intent: Intent) -> bool:
    """Return True when *intent* is unstructured and should use RAG.

    A ``fallback`` intent means no structured intent matched, so the query is a
    general/knowledge question — exactly the case Hybrid RAG handles by falling
    back from Function Calling to knowledge retrieval.
    """
    return intent.name == "fallback"


class HybridRetriever:
    """Knowledge-base retrieval over a VectorStore."""

    def __init__(self, vector_store: VectorStore, embedding: EmbeddingService) -> None:
        self._store = vector_store
        self._embedding = embedding

    async def ingest(self, doc_id: str, text: str) -> None:
        """Embed and store one knowledge document under *doc_id*."""
        vector = await self._embedding.embed_text(text)
        self._store.add(doc_id, text, vector)

    async def retrieve(self, query: str, top_k: int = 3) -> list[SearchResult]:
        """Return the top-k knowledge documents most similar to *query*."""
        vector = await self._embedding.embed_text(query)
        return self._store.search(vector, top_k)

    async def retrieve_reranked(
        self,
        query: str,
        reranker: Reranker,
        recall_k: int = 10,
        top_n: int = 3,
    ) -> list[SearchResult]:
        """Recall *recall_k* candidates, then re-rank down to *top_n* (feat-047)."""
        candidates = await self.retrieve(query, recall_k)
        return reranker.rerank(query, candidates, top_n)
