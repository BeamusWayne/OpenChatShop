"""Unit tests for channel adapters (base, web, wechat)."""
from __future__ import annotations

import pytest

from commerce_agent.core.types import (
    AgentMessage,
    ChannelCapabilities,
    ChannelMessage,
)
from commerce_agent.channel.base import ChannelAdapter
from commerce_agent.channel.web import WebAdapter, WechatAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_msg() -> AgentMessage:
    return AgentMessage(
        message_type="text",
        payload={"content": "hello"},
        text_fallback="hello",
    )


def _product_card_msg() -> AgentMessage:
    return AgentMessage(
        message_type="product_card",
        payload={"product_id": "p1", "name": "Widget", "price": 9.99},
        text_fallback="Widget - 9.99",
    )


def _carousel_msg() -> AgentMessage:
    return AgentMessage(
        message_type="carousel",
        payload={"items": [{"id": "p1"}, {"id": "p2"}]},
        text_fallback="See product list",
    )


# ---------------------------------------------------------------------------
# ChannelAdapter ABC
# ---------------------------------------------------------------------------


class TestChannelAdapterABC:
    """Verify that ChannelAdapter cannot be instantiated directly."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            ChannelAdapter()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# WebAdapter
# ---------------------------------------------------------------------------


class TestWebAdapter:
    def setup_method(self) -> None:
        self.adapter = WebAdapter()

    # -- capabilities ---------------------------------------------------

    def test_supports_all_11_types(self) -> None:
        caps = self.adapter.get_capabilities()
        assert len(caps.supported_types) == 11
        expected = [
            "text", "product_card", "product_list", "order_card",
            "logistics_timeline", "confirm", "form", "rating",
            "transfer", "carousel", "quick_replies",
        ]
        assert caps.supported_types == expected

    def test_capabilities_flags(self) -> None:
        caps = self.adapter.get_capabilities()
        assert caps.supports_rich_text is True
        assert caps.supports_images is True
        assert caps.supports_forms is True
        assert caps.max_message_length == 4096

    # -- adapt ----------------------------------------------------------

    def test_adapt_text(self) -> None:
        msg = _text_msg()
        result = self.adapter.adapt(msg)
        assert result.channel == "web"
        assert result.content_type == "text"
        assert result.payload == {"type": "text", "content": "hello"}
        assert result.was_downgraded is False

    def test_adapt_product_card(self) -> None:
        msg = _product_card_msg()
        result = self.adapter.adapt(msg)
        assert result.content_type == "product_card"
        assert result.payload["product_id"] == "p1"
        assert result.was_downgraded is False

    def test_adapt_preserves_payload_fields(self) -> None:
        msg = AgentMessage(
            message_type="order_card",
            payload={"order_id": "ORD-1", "status": "shipped"},
            text_fallback="Order ORD-1 shipped",
        )
        result = self.adapter.adapt(msg)
        assert result.payload["type"] == "order_card"
        assert result.payload["order_id"] == "ORD-1"
        assert result.payload["status"] == "shipped"

    # -- downgrade ------------------------------------------------------

    def test_downgrade_returns_text(self) -> None:
        msg = _carousel_msg()
        result = self.adapter.downgrade(msg)
        assert result.content_type == "text"
        assert result.was_downgraded is True
        assert result.original_type == "carousel"
        assert result.payload["content"] == "See product list"

    # -- adapt_with_fallback --------------------------------------------

    def test_fallback_uses_adapt_for_supported(self) -> None:
        msg = _product_card_msg()
        result = self.adapter.adapt_with_fallback(msg)
        assert result.was_downgraded is False
        assert result.content_type == "product_card"

    def test_fallback_downgrades_for_unknown_type(self) -> None:
        msg = AgentMessage(
            message_type="hologram_3d",
            payload={"data": "..."},
            text_fallback="3D not available",
        )
        result = self.adapter.adapt_with_fallback(msg)
        assert result.was_downgraded is True
        assert result.content_type == "text"
        assert result.original_type == "hologram_3d"


# ---------------------------------------------------------------------------
# WechatAdapter
# ---------------------------------------------------------------------------


class TestWechatAdapter:
    def setup_method(self) -> None:
        self.adapter = WechatAdapter()

    def test_supports_only_3_types(self) -> None:
        caps = self.adapter.get_capabilities()
        assert caps.supported_types == ["text", "product_card", "order_card"]

    def test_capabilities_limited(self) -> None:
        caps = self.adapter.get_capabilities()
        assert caps.supports_rich_text is False
        assert caps.supports_images is False
        assert caps.supports_forms is False
        assert caps.max_message_length == 2048

    def test_adapt_text(self) -> None:
        msg = _text_msg()
        result = self.adapter.adapt(msg)
        assert result.channel == "wechat"
        assert result.content_type == "text"
        assert result.was_downgraded is False

    def test_adapt_product_card_supported(self) -> None:
        msg = _product_card_msg()
        result = self.adapter.adapt(msg)
        assert result.content_type == "product_card"
        assert result.was_downgraded is False

    def test_downgrade_carousel(self) -> None:
        msg = _carousel_msg()
        result = self.adapter.downgrade(msg)
        assert result.content_type == "text"
        assert result.was_downgraded is True
        assert result.original_type == "carousel"

    def test_fallback_adapts_supported(self) -> None:
        msg = _product_card_msg()
        result = self.adapter.adapt_with_fallback(msg)
        assert result.was_downgraded is False

    def test_fallback_downgrades_unsupported(self) -> None:
        msg = _carousel_msg()
        result = self.adapter.adapt_with_fallback(msg)
        assert result.was_downgraded is True
        assert result.content_type == "text"

    def test_fallback_downgrades_form(self) -> None:
        msg = AgentMessage(
            message_type="form",
            payload={"fields": []},
            text_fallback="Please fill the form",
        )
        result = self.adapter.adapt_with_fallback(msg)
        assert result.was_downgraded is True
        assert result.content_type == "text"
