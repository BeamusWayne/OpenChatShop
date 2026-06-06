"""Tests for PersonaExtractor (feat-053, V2.0 module 3).

After a conversation ends, an LLM summarises the user's stable traits into
persona attributes and they are merged into storage. The extractor must be
robust: a missing provider, an empty conversation, or malformed model output
must never corrupt the persona — it just extracts nothing.
"""
from __future__ import annotations

import asyncio

import pytest

from open_chat_shop.core.persona_extractor import PersonaExtractor
from open_chat_shop.core.provider import MockProvider
from open_chat_shop.storage.persona import InMemoryPersonaRepository

_UTTERANCES = ["我穿 L 码", "有没有便宜点的", "喜欢日系简约风"]


@pytest.mark.unit
class TestPersonaExtractor:
    @pytest.mark.asyncio
    async def test_extracts_and_upserts(self) -> None:
        repo = InMemoryPersonaRepository()
        provider = MockProvider(default_response='{"size": "L", "style": "日系简约"}')
        extractor = PersonaExtractor(provider, repo)
        attrs = await extractor.extract("u1", _UTTERANCES)
        assert attrs == {"size": "L", "style": "日系简约"}
        assert repo.get("u1") == {"size": "L", "style": "日系简约"}

    @pytest.mark.asyncio
    async def test_handles_json_wrapped_in_text(self) -> None:
        repo = InMemoryPersonaRepository()
        provider = MockProvider(default_response='好的，画像如下：{"size": "M"} 以上。')
        attrs = await PersonaExtractor(provider, repo).extract("u1", _UTTERANCES)
        assert attrs == {"size": "M"}

    @pytest.mark.asyncio
    async def test_no_provider_is_noop(self) -> None:
        repo = InMemoryPersonaRepository()
        attrs = await PersonaExtractor(None, repo).extract("u1", _UTTERANCES)
        assert attrs == {}
        assert repo.get("u1") is None

    @pytest.mark.asyncio
    async def test_empty_conversation_is_noop(self) -> None:
        repo = InMemoryPersonaRepository()
        attrs = await PersonaExtractor(MockProvider(), repo).extract("u1", [])
        assert attrs == {}
        assert repo.get("u1") is None

    @pytest.mark.asyncio
    async def test_malformed_output_does_not_corrupt(self) -> None:
        repo = InMemoryPersonaRepository()
        provider = MockProvider(default_response="抱歉我无法总结")  # no JSON
        attrs = await PersonaExtractor(provider, repo).extract("u1", _UTTERANCES)
        assert attrs == {}
        assert repo.get("u1") is None

    @pytest.mark.asyncio
    async def test_non_string_values_are_filtered(self) -> None:
        repo = InMemoryPersonaRepository()
        provider = MockProvider(default_response='{"size": "L", "age": 30, "vip": true}')
        attrs = await PersonaExtractor(provider, repo).extract("u1", _UTTERANCES)
        assert attrs == {"size": "L"}  # only string values survive

    @pytest.mark.asyncio
    async def test_schedule_runs_in_background(self) -> None:
        repo = InMemoryPersonaRepository()
        provider = MockProvider(default_response='{"size": "L"}')
        extractor = PersonaExtractor(provider, repo)
        extractor.schedule("u1", _UTTERANCES)
        # Let the fire-and-forget task run to completion.
        await asyncio.sleep(0.01)
        assert repo.get("u1") == {"size": "L"}
