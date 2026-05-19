"""Intent recognition engine with three-level cascade strategy.

Implements contracts.md section 9: IntentEngine ABC and CascadeIntentEngine.

Cascade levels:
  1. Rule-based matching (regex/keyword) -- threshold 0.85
  2. Semantic similarity (sample overlap) -- threshold 0.7
  3. LLM classification -- threshold 0.5
  Fallback: intent with name "fallback", display_name "未识别", confidence 0.0
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from open_chat_shop.core.exceptions import IntentError
from open_chat_shop.core.types import (
    Intent,
    IntentInfo,
    Message,
    SessionContext,
    UserMessage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------


class IntentEngine(ABC):
    """Abstract base class for intent recognition engines."""

    @abstractmethod
    async def classify(self, message: UserMessage, context: SessionContext) -> Intent:
        """Classify user intent.

        Returns a fallback intent if all recognition levels fail.
        """

    @abstractmethod
    def get_supported_intents(self) -> list[IntentInfo]:
        """Return metadata for every registered intent."""

    @abstractmethod
    async def add_samples(self, intent_name: str, samples: list[str]) -> None:
        """Append training samples for a given intent."""


# ---------------------------------------------------------------------------
# Level 1 -- Rule-based matcher
# ---------------------------------------------------------------------------


class RuleBasedMatcher:
    """Level 1: keyword / regex matching with weighted scoring."""

    def __init__(self) -> None:
        # intent_name -> list of (compiled_pattern, weight)
        self._rules: dict[str, list[tuple[re.Pattern[str], float]]] = {}

    # -- mutators --

    def add_rule(self, intent_name: str, pattern: str, weight: float = 1.0) -> None:
        """Register a regex *pattern* for *intent_name* with the given *weight*."""
        if intent_name not in self._rules:
            self._rules[intent_name] = []
        self._rules[intent_name].append((re.compile(pattern, re.IGNORECASE), weight))

    # -- query --

    def match(self, text: str) -> Intent | None:
        """Return the best-matching Intent with extracted entities, or *None*."""
        scores: dict[str, float] = {}
        for intent_name, patterns in self._rules.items():
            for pattern, weight in patterns:
                if pattern.search(text):
                    scores[intent_name] = scores.get(intent_name, 0.0) + weight

        if not scores:
            return None

        best_intent = max(scores, key=lambda k: scores[k])
        max_score = scores[best_intent]
        total_score = sum(scores.values())
        confidence = max_score / total_score if total_score > 0 else 0.0

        entities = _extract_entities(text, best_intent)

        return Intent(
            name=best_intent,
            display_name=best_intent,
            confidence=confidence,
            source="rule",
            entities=entities,
        )


# ---------------------------------------------------------------------------
# Cascade implementation
# ---------------------------------------------------------------------------


class CascadeIntentEngine(IntentEngine):
    """Three-level cascade: rules -> semantic -> LLM.

    Each level has a confidence threshold.  If the level produces a
    confidence below the threshold it escalates to the next level.
    """

    def __init__(
        self,
        rule_matcher: RuleBasedMatcher,
        level1_threshold: float = 0.85,
        level2_threshold: float = 0.70,
        level3_threshold: float = 0.50,
    ) -> None:
        self._rule_matcher = rule_matcher
        self._level1_threshold = level1_threshold
        self._level2_threshold = level2_threshold
        self._level3_threshold = level3_threshold

        self._intent_registry: dict[str, IntentInfo] = {}
        self._samples: dict[str, list[str]] = {}

        # LLM provider for levels 2/3 -- set via set_provider()
        self._provider: Any = None

    def set_provider(self, provider: Any) -> None:
        """Inject an LLM provider (LLMProvider protocol)."""
        self._provider = provider

    # -- IntentEngine interface -------------------------------------------

    async def classify(self, message: UserMessage, context: SessionContext) -> Intent:
        """Run the three-level cascade and return the best Intent."""
        # Level 1: Rule matching
        rule_result = self._rule_matcher.match(message.content)
        if rule_result is not None and rule_result.confidence >= self._level1_threshold:
            logger.info(
                "Intent resolved at level 1 (rule)",
                extra={"intent": rule_result.name, "confidence": rule_result.confidence},
            )
            return self._enrich_with_context(rule_result, context)

        # Level 2: Semantic similarity over samples
        semantic_result = await self._semantic_search(message.content)
        if semantic_result is not None and semantic_result.confidence >= self._level2_threshold:
            logger.info(
                "Intent resolved at level 2 (semantic)",
                extra={"intent": semantic_result.name, "confidence": semantic_result.confidence},
            )
            return self._enrich_with_context(semantic_result, context)

        # Level 3: LLM classification (only when provider is available)
        if self._provider is not None:
            llm_result = await self._llm_classify(message, context)
            if llm_result is not None and llm_result.confidence >= self._level3_threshold:
                logger.info(
                    "Intent resolved at level 3 (LLM)",
                    extra={"intent": llm_result.name, "confidence": llm_result.confidence},
                )
                return llm_result

        # Fallback
        logger.warning("All intent levels failed, returning fallback")
        return Intent(name="fallback", display_name="未识别", confidence=0.0, source="rule")

    def get_supported_intents(self) -> list[IntentInfo]:
        return list(self._intent_registry.values())

    async def add_samples(self, intent_name: str, samples: list[str]) -> None:
        if intent_name not in self._samples:
            self._samples[intent_name] = []
        self._samples[intent_name].extend(samples)

    def register_intent(self, info: IntentInfo) -> None:
        """Register an intent in the engine's metadata registry."""
        self._intent_registry[info.name] = info

    # -- Level 2: semantic search ----------------------------------------

    async def _semantic_search(self, text: str) -> Intent | None:
        """Simplified semantic search using Jaccard-like word overlap."""
        if not self._samples:
            return None

        best_intent: str | None = None
        best_score = 0.0

        text_words = set(text.lower().split())

        for intent_name, samples in self._samples.items():
            for sample in samples:
                sample_words = set(sample.lower().split())
                overlap = len(sample_words & text_words)
                total = len(sample_words | text_words)
                score = overlap / total if total > 0 else 0.0

                if score > best_score:
                    best_score = score
                    best_intent = intent_name

        if best_intent is not None and best_score > 0:
            return Intent(
                name=best_intent,
                display_name=best_intent,
                confidence=best_score,
                source="semantic",
            )
        return None

    # -- Level 3: LLM classification -------------------------------------

    async def _llm_classify(self, message: UserMessage, context: SessionContext) -> Intent | None:
        """LLM-based intent classification.

        Constructs a classification prompt and calls the provider.
        Returns *None* if the provider call fails or the response
        cannot be parsed.
        """
        try:
            intent_names = list(self._intent_registry.keys()) or ["fallback"]
            prompt = (
                "Classify the following user message into one of these intents: "
                + ", ".join(intent_names)
                + ".\n\n"
                f"User message: {message.content}\n\n"
                "Respond with ONLY the intent name."
            )

            messages = [Message(role="user", content=prompt)]
            response = await self._provider.chat(messages)

            predicted = response.content.strip().lower()
            for registered_name in intent_names:
                if registered_name.lower() == predicted:
                    return Intent(
                        name=registered_name,
                        display_name=registered_name,
                        confidence=0.75,
                        source="llm",
                    )

            # Could not map the LLM response to a known intent
            logger.warning("LLM returned unmapped intent: %s", predicted)
            return None

        except Exception:
            logger.exception("LLM classification failed")
            return None

    # -- context enrichment -----------------------------------------------

    @staticmethod
    def _enrich_with_context(intent: Intent, context: SessionContext) -> Intent:
        """Merge session context entities (slots, recent history) into the Intent."""
        entities: dict[str, Any] = dict(intent.entities)

        # Carry over slot data that the intent might need
        for key, value in context.slots.items():
            if key not in entities:
                entities[key] = value

        # Check recent assistant messages for disambiguation signals
        for msg in reversed(context.history[-3:]):
            if msg.role == "assistant" and "请问" in msg.content:
                # The agent asked a clarifying question -- current intent
                # is likely the user's answer to that question
                entities["_clarifying_response"] = True
                break

        return Intent(
            name=intent.name,
            display_name=intent.display_name,
            confidence=intent.confidence,
            source=intent.source,
            entities=entities,
        )


# ---------------------------------------------------------------------------
# Entity extraction helpers
# ---------------------------------------------------------------------------

_ORDER_ID_RE = re.compile(r"ORD-[\w]+", re.IGNORECASE)
_PRODUCT_KEYWORD_RE = re.compile(
    r"(?:搜索?|查找?|找一下|有没有|想买|来[一几]个|search)\s*(.+)", re.IGNORECASE
)


def _extract_entities(text: str, intent_name: str) -> dict[str, Any]:
    """Extract relevant entities from *text* based on *intent_name*.

    Uses simple regex patterns to pull out order IDs, search keywords, etc.
    Returns an empty dict if nothing relevant is found.
    """
    entities: dict[str, Any] = {}

    if intent_name in ("query_order", "query_logistics", "cancel_order",
                       "check_refund_eligibility", "create_refund", "modify_address"):
        m = _ORDER_ID_RE.search(text)
        if m:
            entities["order_id"] = m.group(0)

    if intent_name == "search_product":
        # Try to extract keyword after the trigger word
        m = _PRODUCT_KEYWORD_RE.search(text)
        if m:
            entities["keyword"] = m.group(1).strip()

    return entities
