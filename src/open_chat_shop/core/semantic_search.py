"""Semantic search for intent engine Level 1.

Provides EmbeddingService and InMemoryVectorStore as alternatives to
the Jaccard word-overlap matching in the base CascadeIntentEngine.
Designed to be swapped in when a real embedding provider is available.
"""
from __future__ import annotations

import heapq
import logging
import math
from dataclasses import dataclass
from typing import Any, cast

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single result from semantic search."""
    intent: str
    score: float
    text: str


class InMemoryVectorStore:
    """Simple in-memory vector store using cosine similarity.

    Suitable for development and testing. For production, replace
    with pgvector or Milvus.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension
        self._vectors: dict[str, list[list[float]]] = {}  # intent -> list of vectors
        self._texts: dict[str, list[str]] = {}  # intent -> list of original texts

    def add(self, intent: str, text: str, vector: list[float]) -> None:
        """Add a text sample with its embedding for a given intent."""
        if intent not in self._vectors:
            self._vectors[intent] = []
            self._texts[intent] = []
        self._vectors[intent].append(vector)
        self._texts[intent].append(text)

    def search(self, query_vector: list[float], top_k: int = 3) -> list[SearchResult]:
        """Find the top-k most similar samples across all intents.

        This is a dev/test store (production should route to pgvector/Milvus,
        per the class docstring). Scoring is still a full linear scan, but we use
        a bounded top-k heap (``heapq.nlargest``) instead of sorting every
        result, so cost is O(n log top_k) rather than O(n log n) on the sort.
        """
        results = (
            SearchResult(
                intent=intent,
                score=_cosine_similarity(query_vector, vec),
                text=self._texts[intent][i],
            )
            for intent, vectors in self._vectors.items()
            for i, vec in enumerate(vectors)
        )
        return heapq.nlargest(top_k, results, key=lambda r: r.score)

    def get_intents(self) -> list[str]:
        """Return all registered intents."""
        return list(self._vectors.keys())

    def clear(self, intent: str | None = None) -> None:
        """Clear vectors for a specific intent or all intents."""
        if intent is None:
            self._vectors.clear()
            self._texts.clear()
        else:
            self._vectors.pop(intent, None)
            self._texts.pop(intent, None)


class EmbeddingService:
    """Wraps an LLM provider's embed() method for semantic search.

    Provides a simple interface: embed_text() returns a vector,
    which can then be used with InMemoryVectorStore.search().
    """

    def __init__(self, provider: Any = None, fallback_dimension: int = 384) -> None:
        self._provider = provider
        self._fallback_dim = fallback_dimension

    async def embed_text(self, text: str) -> list[float]:
        """Get embedding for a single text string."""
        if self._provider is not None:
            embeddings = await self._provider.embed([text])
            return cast("list[float]", embeddings[0])
        # Fallback: simple bag-of-words hashing for testing
        return self._simple_hash_embedding(text)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts."""
        if self._provider is not None:
            return cast("list[list[float]]", await self._provider.embed(texts))
        return [self._simple_hash_embedding(t) for t in texts]

    def _simple_hash_embedding(self, text: str) -> list[float]:
        """Deterministic hash-based embedding for testing without a real model."""
        dim = self._fallback_dim
        vec = [0.0] * dim
        for char in text:
            idx = ord(char) % dim
            vec[idx] += 1.0
        # Normalize
        magnitude = math.sqrt(sum(v * v for v in vec))
        if magnitude > 0:
            vec = [v / magnitude for v in vec]
        return vec


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
