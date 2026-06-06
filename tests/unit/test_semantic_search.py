"""Tests for semantic search — InMemoryVectorStore and EmbeddingService."""
from __future__ import annotations

import math

import pytest

from open_chat_shop.core.provider import MockProvider
from open_chat_shop.core.semantic_search import (
    EmbeddingService,
    InMemoryVectorStore,
    _cosine_similarity,
)

# ===========================================================================
# Cosine similarity
# ===========================================================================


class TestCosineSimilarity:
    @pytest.mark.unit
    def test_identical_vectors(self):
        vec = [1.0, 0.0, 0.0]
        assert _cosine_similarity(vec, vec) == pytest.approx(1.0)

    @pytest.mark.unit
    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    @pytest.mark.unit
    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    @pytest.mark.unit
    def test_zero_vector(self):
        assert _cosine_similarity([0, 0], [1, 0]) == 0.0


# ===========================================================================
# InMemoryVectorStore
# ===========================================================================


class TestInMemoryVectorStore:
    @pytest.mark.unit
    def test_add_and_search(self):
        store = InMemoryVectorStore(dimension=4)
        # Intent A vectors point in [1,0,0,0] direction
        store.add("query_order", "查询订单", [1.0, 0.0, 0.0, 0.0])
        store.add("query_order", "我的订单在哪", [0.9, 0.1, 0.0, 0.0])
        # Intent B vectors point in [0,1,0,0] direction
        store.add("refund", "我要退款", [0.0, 1.0, 0.0, 0.0])

        results = store.search([1.0, 0.0, 0.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0].intent == "query_order"
        assert results[0].score > results[1].score

    @pytest.mark.unit
    def test_search_returns_top_k(self):
        store = InMemoryVectorStore(dimension=3)
        for i in range(10):
            vec = [0.0] * 3
            vec[i % 3] = 1.0
            store.add(f"intent_{i}", f"text_{i}", vec)

        results = store.search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3

    @pytest.mark.unit
    def test_search_empty_store(self):
        store = InMemoryVectorStore()
        results = store.search([1.0, 0.0], top_k=5)
        assert results == []

    @pytest.mark.unit
    def test_get_intents(self):
        store = InMemoryVectorStore()
        store.add("a", "text", [1.0])
        store.add("b", "text", [1.0])
        assert set(store.get_intents()) == {"a", "b"}

    @pytest.mark.unit
    def test_clear_specific_intent(self):
        store = InMemoryVectorStore()
        store.add("a", "text", [1.0])
        store.add("b", "text", [1.0])
        store.clear("a")
        assert store.get_intents() == ["b"]

    @pytest.mark.unit
    def test_clear_all(self):
        store = InMemoryVectorStore()
        store.add("a", "text", [1.0])
        store.add("b", "text", [1.0])
        store.clear()
        assert store.get_intents() == []


# ===========================================================================
# EmbeddingService
# ===========================================================================


class TestEmbeddingService:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_embed_text_without_provider(self):
        """Fallback hash embedding works without a provider."""
        service = EmbeddingService(fallback_dimension=16)
        vec = await service.embed_text("hello")
        assert len(vec) == 16
        # Normalized vector has unit magnitude
        mag = math.sqrt(sum(v * v for v in vec))
        assert mag == pytest.approx(1.0, abs=0.01)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_embed_texts_without_provider(self):
        service = EmbeddingService(fallback_dimension=8)
        vecs = await service.embed_texts(["hello", "world"])
        assert len(vecs) == 2
        assert len(vecs[0]) == 8

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_embed_text_with_provider(self):
        """Uses provider.embed() when available."""
        provider = MockProvider(default_embeddings=[[0.5] * 10])
        service = EmbeddingService(provider=provider)
        vec = await service.embed_text("test")
        assert len(vec) == 10
        assert vec[0] == 0.5

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_embed_texts_with_provider(self):
        provider = MockProvider(default_embeddings=[[0.3] * 8])
        service = EmbeddingService(provider=provider)
        vecs = await service.embed_texts(["a", "b"])
        assert len(vecs) == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hash_embedding_deterministic(self):
        service = EmbeddingService(fallback_dimension=16)
        v1 = await service.embed_text("same text")
        v2 = await service.embed_text("same text")
        assert v1 == v2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_hash_embedding_different_texts_differ(self):
        service = EmbeddingService(fallback_dimension=16)
        v1 = await service.embed_text("text one")
        v2 = await service.embed_text("text two")
        assert v1 != v2


# ===========================================================================
# Integration: EmbeddingService + InMemoryVectorStore
# ===========================================================================


class TestSemanticSearchIntegration:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_end_to_end_search(self):
        """Full pipeline: embed texts -> store -> search -> get results."""
        service = EmbeddingService(fallback_dimension=16)
        store = InMemoryVectorStore(dimension=16)

        # Add samples for two intents
        samples = {
            "query_order": ["查询订单状态", "我的快递到哪了", "物流信息"],
            "refund": ["申请退款", "退货退款", "不想要了要退钱"],
        }
        for intent, texts in samples.items():
            for text in texts:
                vec = await service.embed_text(text)
                store.add(intent, text, vec)

        # Search for order-related query
        query_vec = await service.embed_text("查一下我的订单")
        results = store.search(query_vec, top_k=3)

        assert len(results) > 0
        # The top result should be query_order intent
        assert results[0].intent == "query_order"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_different_queries_yield_different_intents(self):
        service = EmbeddingService(fallback_dimension=16)
        store = InMemoryVectorStore(dimension=16)

        # Use very different text patterns
        store.add("aaa", "aaa aaa aaa", await service.embed_text("aaa aaa aaa"))
        store.add("bbb", "bbb bbb bbb", await service.embed_text("bbb bbb bbb"))

        result_a = store.search(await service.embed_text("aaa"), top_k=1)
        result_b = store.search(await service.embed_text("bbb"), top_k=1)

        assert result_a[0].intent == "aaa"
        assert result_b[0].intent == "bbb"
