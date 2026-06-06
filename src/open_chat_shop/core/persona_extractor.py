"""Async user-persona extraction (V2.0 module 3, feat-053).

After a conversation ends (or the user goes idle), an LLM summarises the user's
stable preference traits — size, price sensitivity, style, category interest —
into persona attributes that are merged into storage for next time. The model
is injected, so production can use a cheap/small model.

Robustness is the priority: a missing provider, an empty conversation, a failed
call, or malformed output must never corrupt the persona — they extract nothing.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from open_chat_shop.core.types import Message
from open_chat_shop.storage.persona import PersonaRepository

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是用户画像提取助手。从对话中总结用户稳定的偏好特征"
    "（如尺码、价格敏感度、风格偏好、品类兴趣）。"
    "只输出一个 JSON 对象，键和值都是字符串；无法确定的特征不要包含；不要输出多余文字。"
)


def _parse_attributes(text: str) -> dict[str, str]:
    """Extract a JSON object of string->string attributes from model output.

    Tolerant of surrounding prose; returns ``{}`` on any failure so a bad model
    response can never write garbage into a persona. Non-string values are
    dropped (a persona is ``dict[str, str]``).
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str)}


class PersonaExtractor:
    """Summarise a conversation into persona attributes and persist them."""

    def __init__(self, provider: Any, repo: PersonaRepository) -> None:
        self._provider = provider
        self._repo = repo
        self._tasks: set[asyncio.Task[Any]] = set()

    async def extract(self, user_id: str, utterances: list[str]) -> dict[str, str]:
        """Summarise *utterances* into attributes, merge into the persona.

        Returns the newly extracted attributes ({} when nothing was extracted).
        """
        if self._provider is None or not utterances:
            return {}
        transcript = "\n".join(utterances)
        messages = [
            Message(role="system", content=_SYSTEM_PROMPT),
            Message(role="user", content=f"对话记录：\n{transcript}\n请输出画像 JSON："),
        ]
        try:
            response = await self._provider.chat(messages)
        except Exception:
            logger.warning("Persona extraction LLM call failed; skipping")
            return {}
        attrs = _parse_attributes(response.content)
        if attrs:
            self._repo.upsert(user_id, attrs)
        return attrs

    def schedule(self, user_id: str, utterances: list[str]) -> None:
        """Run extraction as a fire-and-forget background task.

        The task is kept in a set (and removed on completion) so it is not
        garbage-collected mid-flight.
        """
        task = asyncio.create_task(self.extract(user_id, utterances))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
