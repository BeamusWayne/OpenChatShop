"""WeChat Mini Program channel adapter — rich message rendering."""
from __future__ import annotations

from typing import ClassVar

from open_chat_shop.channel.base import ChannelAdapter
from open_chat_shop.core.types import (
    AgentMessage,
    ChannelCapabilities,
    ChannelMessage,
)


class MiniProgramAdapter(ChannelAdapter):
    """Channel adapter for WeChat Mini Program.

    Supported message types: text, product_card, order_card,
    logistics_timeline, rating, quick_replies.

    Unsupported types fall back to plain text via *downgrade*.
    """

    SUPPORTED_TYPES: ClassVar[list[str]] = [
        "text",
        "product_card",
        "order_card",
        "logistics_timeline",
        "rating",
        "quick_replies",
    ]

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    def get_capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            supported_types=list(self.SUPPORTED_TYPES),
            supports_rich_text=True,
            supports_images=True,
            supports_forms=False,
            max_message_length=2048,
        )

    def adapt(self, message: AgentMessage) -> ChannelMessage:
        renderer = self._RENDERERS.get(message.message_type)
        if renderer is not None:
            payload = renderer(self, message)
        else:
            payload = self._render_fallback_text(message)
        return ChannelMessage(
            channel="miniprogram",
            content_type=message.message_type if renderer else "text",
            payload=payload,
            was_downgraded=renderer is None,
            original_type=(
                message.message_type if renderer is None else None
            ),
        )

    def downgrade(self, message: AgentMessage) -> ChannelMessage:
        return ChannelMessage(
            channel="miniprogram",
            content_type="text",
            payload={
                "msgtype": "text",
                "text": {"content": message.text_fallback},
            },
            was_downgraded=True,
            original_type=message.message_type,
        )

    # ------------------------------------------------------------------
    # Per-type render helpers
    # ------------------------------------------------------------------

    def _render_fallback_text(self, message: AgentMessage) -> dict:
        """Render unsupported types as plain text using text_fallback."""
        return {
            "msgtype": "text",
            "text": {"content": message.text_fallback},
        }

    def _render_text(self, message: AgentMessage) -> dict:
        return {
            "msgtype": "text",
            "text": {"content": message.payload.get("content", "")},
        }

    def _render_product_card(self, message: AgentMessage) -> dict:
        p = message.payload
        return {
            "msgtype": "miniprogram_data",
            "miniprogram_data": {
                "title": p.get("name", ""),
                "price": p.get("price", 0),
                "image_url": p.get("image_url", ""),
                "product_id": p.get("product_id", ""),
            },
        }

    def _render_order_card(self, message: AgentMessage) -> dict:
        p = message.payload
        return {
            "msgtype": "miniprogram_data",
            "miniprogram_data": {
                "order_id": p.get("order_id", ""),
                "status": p.get("status", ""),
                "items": p.get("items", []),
            },
        }

    def _render_logistics_timeline(self, message: AgentMessage) -> dict:
        p = message.payload
        return {
            "msgtype": "miniprogram_data",
            "miniprogram_data": {
                "order_id": p.get("order_id", ""),
                "steps": p.get("steps", []),
            },
        }

    def _render_rating(self, message: AgentMessage) -> dict:
        p = message.payload
        return {
            "msgtype": "miniprogram_data",
            "miniprogram_data": {
                "score": p.get("score", 0),
                "comment": p.get("comment", ""),
            },
        }

    def _render_quick_replies(self, message: AgentMessage) -> dict:
        p = message.payload
        return {
            "msgtype": "miniprogram_data",
            "miniprogram_data": {
                "options": p.get("options", []),
            },
        }

    # Map message_type -> render method
    _RENDERERS: ClassVar[dict[str, object]] = {
        "text": _render_text,
        "product_card": _render_product_card,
        "order_card": _render_order_card,
        "logistics_timeline": _render_logistics_timeline,
        "rating": _render_rating,
        "quick_replies": _render_quick_replies,
    }
