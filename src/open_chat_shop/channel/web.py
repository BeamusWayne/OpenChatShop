"""Web and WeChat channel adapters."""
from __future__ import annotations

from open_chat_shop.core.types import (
    AgentMessage,
    ChannelCapabilities,
    ChannelMessage,
)

from open_chat_shop.channel.base import ChannelAdapter


class WebAdapter(ChannelAdapter):
    """Web channel adapter — supports all 11 message types from contracts.md section 12."""

    SUPPORTED_TYPES = [
        "text",
        "product_card",
        "product_list",
        "order_card",
        "logistics_timeline",
        "confirm",
        "form",
        "rating",
        "transfer",
        "carousel",
        "quick_replies",
    ]

    def get_capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            supported_types=list(self.SUPPORTED_TYPES),
            supports_rich_text=True,
            supports_images=True,
            supports_forms=True,
            max_message_length=4096,
        )

    def adapt(self, message: AgentMessage) -> ChannelMessage:
        """Convert to web JSON payload."""
        return ChannelMessage(
            channel="web",
            content_type=message.message_type,
            payload={"type": message.message_type, **message.payload},
            was_downgraded=False,
        )

    def downgrade(self, message: AgentMessage) -> ChannelMessage:
        """Downgrade to plain text."""
        return ChannelMessage(
            channel="web",
            content_type="text",
            payload={"type": "text", "content": message.text_fallback},
            was_downgraded=True,
            original_type=message.message_type,
        )


class WechatAdapter(ChannelAdapter):
    """WeChat channel adapter — limited to text, product_card, order_card.

    All other types are downgraded to plain text.
    """

    SUPPORTED_TYPES = [
        "text",
        "product_card",
        "order_card",
    ]

    def get_capabilities(self) -> ChannelCapabilities:
        return ChannelCapabilities(
            supported_types=list(self.SUPPORTED_TYPES),
            supports_rich_text=False,
            supports_images=False,
            supports_forms=False,
            max_message_length=2048,
        )

    def adapt(self, message: AgentMessage) -> ChannelMessage:
        """Convert to WeChat-compatible payload."""
        return ChannelMessage(
            channel="wechat",
            content_type=message.message_type,
            payload={"type": message.message_type, **message.payload},
            was_downgraded=False,
        )

    def downgrade(self, message: AgentMessage) -> ChannelMessage:
        """Downgrade to plain text for WeChat."""
        return ChannelMessage(
            channel="wechat",
            content_type="text",
            payload={"type": "text", "content": message.text_fallback},
            was_downgraded=True,
            original_type=message.message_type,
        )
