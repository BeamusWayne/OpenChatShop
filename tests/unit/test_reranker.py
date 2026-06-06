"""Tests for RAG re-ranking (feat-047, V2.0 module 2).

After a broad recall (Top-10), a lightweight re-ranker promotes the few most
relevant documents (Top-3) before they are fed to the LLM, cutting noise. The
ABC lets a real cross-encoder slot in; the default degrades safely to "keep the
recall order and truncate".
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.hybrid_retrieval import HybridRetriever
from open_chat_shop.core.reranker import (
    LexicalReranker,
    Reranker,
    TruncateReranker,
)
from open_chat_shop.core.semantic_search import (
    EmbeddingService,
    InMemoryVectorStore,
    SearchResult,
)


def _cand(intent: str, score: float, text: str) -> SearchResult:
    return SearchResult(intent=intent, score=score, text=text)


@pytest.mark.unit
class TestTruncateReranker:
    def test_is_a_reranker(self) -> None:
        assert isinstance(TruncateReranker(), Reranker)

    def test_keeps_recall_order_and_truncates(self) -> None:
        cands = [_cand("a", 0.9, "x"), _cand("b", 0.8, "y"), _cand("c", 0.7, "z")]
        out = TruncateReranker().rerank("q", cands, top_n=2)
        assert [r.intent for r in out] == ["a", "b"]


@pytest.mark.unit
class TestLexicalReranker:
    def test_promotes_most_overlapping_doc(self) -> None:
        # Recall put the irrelevant doc first (higher embedding score), but the
        # lexically-relevant doc must be promoted by the re-ranker.
        cands = [
            _cand("noise", 0.9, "今天天气很好适合出门"),
            _cand("answer", 0.5, "退货政策是七天无理由退货"),
        ]
        out = LexicalReranker().rerank("退货政策", cands, top_n=1)
        assert out[0].intent == "answer"

    def test_top_n_limits(self) -> None:
        cands = [_cand(str(i), 0.5, f"条目{i}") for i in range(5)]
        assert len(LexicalReranker().rerank("条目", cands, top_n=3)) == 3


@pytest.mark.unit
class TestRetrieveRerankedPipeline:
    @pytest.mark.asyncio
    async def test_recall_then_rerank(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore(), EmbeddingService(provider=None))
        for i in range(6):
            await retriever.ingest(f"doc{i}", f"知识条目编号 {i}")
        out = await retriever.retrieve_reranked(
            "知识条目编号 0", TruncateReranker(), recall_k=6, top_n=3
        )
        assert len(out) == 3
