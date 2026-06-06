"""Tests for Hybrid RAG retrieval (feat-046, V2.0 module 2).

Structured queries (an actionable intent) keep using Function Calling; an
unstructured query — one no structured intent matched, i.e. ``fallback`` — is
routed to retrieval over a FAQ / product knowledge base built on the feat-044
VectorStore.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.hybrid_retrieval import HybridRetriever, should_use_rag
from open_chat_shop.core.semantic_search import EmbeddingService, InMemoryVectorStore
from open_chat_shop.core.types import Intent


def _intent(name: str) -> Intent:
    return Intent(name=name, display_name=name, confidence=1.0, source="rule")


@pytest.mark.unit
class TestRouting:
    def test_fallback_uses_rag(self) -> None:
        assert should_use_rag(_intent("fallback")) is True

    @pytest.mark.parametrize("name", ["create_refund", "query_order", "search_product"])
    def test_structured_intent_uses_function_calling(self, name: str) -> None:
        assert should_use_rag(_intent(name)) is False


@pytest.mark.unit
class TestHybridRetriever:
    @pytest.fixture()
    def retriever(self) -> HybridRetriever:
        return HybridRetriever(InMemoryVectorStore(), EmbeddingService(provider=None))

    @pytest.mark.asyncio
    async def test_ingest_then_retrieve_returns_relevant_doc(
        self, retriever: HybridRetriever
    ) -> None:
        await retriever.ingest("faq_return", "退货政策是7天无理由退货")
        await retriever.ingest("faq_shrink", "这款纯棉T恤可能轻微缩水")
        results = await retriever.retrieve("退货政策是7天无理由退货", top_k=1)
        assert results[0].intent == "faq_return"

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self, retriever: HybridRetriever) -> None:
        for i in range(5):
            await retriever.ingest(f"doc{i}", f"知识条目 {i}")
        assert len(await retriever.retrieve("知识条目 0", top_k=2)) == 2

    @pytest.mark.asyncio
    async def test_retrieve_on_empty_kb_returns_empty(
        self, retriever: HybridRetriever
    ) -> None:
        assert await retriever.retrieve("任何问题") == []
