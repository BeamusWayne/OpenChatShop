"""Unit tests for MiniProgramAdapter."""
from __future__ import annotations

from open_chat_shop.channel.miniprogram import MiniProgramAdapter
from open_chat_shop.core.types import AgentMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_msg(msg_type: str, payload: dict, fallback: str = "fallback") -> AgentMessage:
    return AgentMessage(
        message_type=msg_type,
        payload=payload,
        text_fallback=fallback,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMiniProgramAdapter:
    def setup_method(self) -> None:
        self.adapter = MiniProgramAdapter()

    # -- capabilities -------------------------------------------------------

    def test_supported_types(self) -> None:
        caps = self.adapter.get_capabilities()
        expected = [
            "text", "product_card", "order_card",
            "logistics_timeline", "rating", "quick_replies",
        ]
        assert caps.supported_types == expected

    # -- text ---------------------------------------------------------------

    def test_text_message_renders_correctly(self) -> None:
        msg = _make_msg("text", {"content": "Hello, welcome!"})
        result = self.adapter.adapt(msg)
        assert result.channel == "miniprogram"
        assert result.content_type == "text"
        assert result.was_downgraded is False
        assert result.payload["msgtype"] == "text"
        assert result.payload["text"]["content"] == "Hello, welcome!"

    # -- product_card -------------------------------------------------------

    def test_product_card_renders_with_title_price_image(self) -> None:
        msg = _make_msg(
            "product_card",
            {
                "product_id": "p100",
                "name": "Wireless Earbuds",
                "price": 199.0,
                "image_url": "https://example.com/img.jpg",
            },
        )
        result = self.adapter.adapt(msg)
        assert result.content_type == "product_card"
        assert result.was_downgraded is False
        data = result.payload["miniprogram_data"]
        assert data["title"] == "Wireless Earbuds"
        assert data["price"] == 199.0
        assert data["image_url"] == "https://example.com/img.jpg"
        assert data["product_id"] == "p100"

    # -- order_card ---------------------------------------------------------

    def test_order_card_renders_with_order_id_status_items(self) -> None:
        msg = _make_msg(
            "order_card",
            {
                "order_id": "ORD-20240601",
                "status": "shipped",
                "items": [{"name": "Item A", "qty": 2}],
            },
        )
        result = self.adapter.adapt(msg)
        assert result.content_type == "order_card"
        data = result.payload["miniprogram_data"]
        assert data["order_id"] == "ORD-20240601"
        assert data["status"] == "shipped"
        assert data["items"] == [{"name": "Item A", "qty": 2}]

    # -- logistics_timeline -------------------------------------------------

    def test_logistics_timeline_renders_with_steps_array(self) -> None:
        steps = [
            {"status": "picked_up", "time": "2024-06-01T10:00:00Z", "location": "Shanghai"},
            {"status": "in_transit", "time": "2024-06-01T14:00:00Z", "location": "Hangzhou"},
        ]
        msg = _make_msg(
            "logistics_timeline",
            {"order_id": "ORD-1", "steps": steps},
        )
        result = self.adapter.adapt(msg)
        assert result.content_type == "logistics_timeline"
        data = result.payload["miniprogram_data"]
        assert data["order_id"] == "ORD-1"
        assert data["steps"] == steps
        assert len(data["steps"]) == 2

    # -- rating -------------------------------------------------------------

    def test_rating_renders_with_score_and_comment(self) -> None:
        msg = _make_msg(
            "rating",
            {"score": 4, "comment": "Good quality"},
        )
        result = self.adapter.adapt(msg)
        assert result.content_type == "rating"
        data = result.payload["miniprogram_data"]
        assert data["score"] == 4
        assert data["comment"] == "Good quality"

    # -- quick_replies ------------------------------------------------------

    def test_quick_replies_renders_with_options_array(self) -> None:
        options = [
            {"label": "Buy now", "value": "buy"},
            {"label": "Add to cart", "value": "cart"},
        ]
        msg = _make_msg(
            "quick_replies",
            {"options": options},
        )
        result = self.adapter.adapt(msg)
        assert result.content_type == "quick_replies"
        data = result.payload["miniprogram_data"]
        assert data["options"] == options
        assert len(data["options"]) == 2

    # -- unsupported type falls back to text --------------------------------

    def test_unsupported_type_falls_back_to_text(self) -> None:
        msg = _make_msg(
            "carousel",
            {"items": [{"id": "p1"}]},
            fallback="See product list",
        )
        result = self.adapter.adapt(msg)
        assert result.was_downgraded is True
        assert result.content_type == "text"
        assert result.original_type == "carousel"
        assert result.payload["text"]["content"] == "See product list"

    # -- empty payload handled gracefully -----------------------------------

    def test_empty_payload_handled_gracefully(self) -> None:
        msg = _make_msg("text", {})
        result = self.adapter.adapt(msg)
        assert result.content_type == "text"
        assert result.payload["text"]["content"] == ""

    # -- downgrade ----------------------------------------------------------

    def test_downgrade_returns_text(self) -> None:
        msg = _make_msg("form", {"fields": []}, "Fill the form")
        result = self.adapter.downgrade(msg)
        assert result.channel == "miniprogram"
        assert result.content_type == "text"
        assert result.was_downgraded is True
        assert result.original_type == "form"
        assert result.payload["text"]["content"] == "Fill the form"

    # -- adapt_with_fallback ------------------------------------------------

    def test_adapt_with_fallback_supported_type(self) -> None:
        msg = _make_msg("rating", {"score": 5})
        result = self.adapter.adapt_with_fallback(msg)
        assert result.was_downgraded is False
        assert result.content_type == "rating"

    def test_adapt_with_fallback_unsupported_type(self) -> None:
        msg = _make_msg("form", {"fields": []}, "Form not supported")
        result = self.adapter.adapt_with_fallback(msg)
        assert result.was_downgraded is True
        assert result.content_type == "text"
