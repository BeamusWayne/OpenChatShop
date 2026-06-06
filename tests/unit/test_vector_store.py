"""Tests for the VectorStore abstraction (feat-044, V2.0 module 2 foundation).

The existing InMemoryVectorStore is lifted behind a VectorStore ABC so a
production backend (pgvector, feat-045) can be swapped in. The ABC mirrors the
existing concrete API (add / search / get_intents / clear) so the in-memory
store needs no behaviour change and existing callers are unaffected.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.semantic_search import (
    InMemoryVectorStore,
    SearchResult,
    VectorStore,
)


@pytest.mark.unit
class TestVectorStoreAbstraction:
    def test_in_memory_store_is_a_vector_store(self) -> None:
        assert isinstance(InMemoryVectorStore(), VectorStore)

    def test_abstract_base_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            VectorStore()  # type: ignore[abstract]

    def test_custom_backend_is_polymorphic(self) -> None:
        class _FixedStore(VectorStore):
            def add(self, intent, text, vector):
                pass

            def search(self, query_vector, top_k=3):
                return [SearchResult(intent="x", score=1.0, text="hit")]

            def get_intents(self):
                return ["x"]

            def clear(self, intent=None):
                pass

        store: VectorStore = _FixedStore()
        assert store.search([0.1, 0.2])[0].text == "hit"

    def test_in_memory_add_then_search_unchanged(self) -> None:
        # Pin the existing behaviour: adding under the ABC and searching returns
        # the nearest sample, exactly as before the refactor.
        store = InMemoryVectorStore()
        store.add("query_order", "我的订单", [1.0, 0.0, 0.0])
        store.add("refund", "退款", [0.0, 1.0, 0.0])
        results = store.search([1.0, 0.0, 0.0], top_k=1)
        assert results[0].intent == "query_order"
