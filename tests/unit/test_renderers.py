"""Unit tests for MessageRenderer — feat-021."""
from __future__ import annotations

import pytest

from open_chat_shop.channel.renderers import MessageRenderer
from open_chat_shop.core.types import AgentMessage

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(msg_type: str, payload: dict, fallback: str = "fb") -> AgentMessage:
    return AgentMessage(
        message_type=msg_type, payload=payload, text_fallback=fallback,
    )


renderer = MessageRenderer()


# ---------------------------------------------------------------------------
# Happy-path: all 11 types render correctly
# ---------------------------------------------------------------------------


class TestTextRender:
    def test_renders_with_timestamp(self) -> None:
        result = renderer.render(_msg("text", {"content": "hi"}))
        assert result["type"] == "text"
        assert result["payload"]["content"] == "hi"
        assert "timestamp" in result["payload"]


class TestProductCardRender:
    def test_renders_required_fields(self) -> None:
        result = renderer.render(_msg(
            "product_card",
            {"product_id": "p1", "name": "Widget", "price": 9.99},
        ))
        assert result["type"] == "product_card"
        assert result["payload"]["product_id"] == "p1"
        assert result["payload"]["name"] == "Widget"
        assert result["payload"]["price"] == 9.99

    def test_includes_optional_fields(self) -> None:
        result = renderer.render(_msg(
            "product_card",
            {"product_id": "p1", "name": "X", "price": 0,
             "image_url": "http://img", "rating": 4.5, "stock": 10},
        ))
        assert result["payload"]["image_url"] == "http://img"
        assert result["payload"]["rating"] == 4.5
        assert result["payload"]["stock"] == 10


class TestProductListRender:
    def test_renders_matching_length(self) -> None:
        prods = [{"product_id": "p1"}, {"product_id": "p2"}]
        result = renderer.render(_msg("product_list", {"products": prods, "total": 2}))
        assert result["payload"]["total"] == 2
        assert len(result["payload"]["products"]) == 2


class TestOrderCardRender:
    def test_renders_valid_status(self) -> None:
        result = renderer.render(_msg(
            "order_card",
            {"order_id": "O1", "status": "shipped", "total_amount": 100},
        ))
        assert result["payload"]["status"] == "shipped"
        assert result["payload"]["total_amount"] == 100


class TestLogisticsTimelineRender:
    def test_renders_with_steps(self) -> None:
        steps = [{"status": "picked", "time": "10:00", "location": "SH"}]
        result = renderer.render(_msg(
            "logistics_timeline", {"order_id": "O1", "steps": steps},
        ))
        assert result["payload"]["steps"][0]["status"] == "picked"


class TestConfirmRender:
    def test_applies_default_labels(self) -> None:
        result = renderer.render(_msg(
            "confirm", {"title": "OK?", "description": "Sure?"},
        ))
        assert result["payload"]["confirm_label"] == "确认"
        assert result["payload"]["cancel_label"] == "取消"

    def test_uses_custom_labels(self) -> None:
        result = renderer.render(_msg(
            "confirm",
            {"title": "T", "description": "D",
             "confirm_label": "Yes", "cancel_label": "No"},
        ))
        assert result["payload"]["confirm_label"] == "Yes"
        assert result["payload"]["cancel_label"] == "No"


class TestFormRender:
    def test_renders_valid_fields(self) -> None:
        fields = [{"name": "addr", "type": "text", "label": "Address", "required": True}]
        result = renderer.render(_msg("form", {"fields": fields}))
        assert result["payload"]["fields"][0]["name"] == "addr"


class TestRatingRender:
    def test_applies_default_scores(self) -> None:
        result = renderer.render(_msg("rating", {"prompt": "Rate us"}))
        assert result["payload"]["max_score"] == 5
        assert result["payload"]["min_score"] == 1

    def test_uses_custom_scores(self) -> None:
        result = renderer.render(_msg(
            "rating", {"prompt": "Rate", "max_score": 10, "min_score": 0},
        ))
        assert result["payload"]["max_score"] == 10


class TestTransferRender:
    def test_renders_with_optional_fields(self) -> None:
        result = renderer.render(_msg(
            "transfer",
            {"reason": "complex", "estimated_wait_seconds": 120, "department": "VIP"},
        ))
        assert result["payload"]["department"] == "VIP"
        assert result["payload"]["estimated_wait_seconds"] == 120


class TestCarouselRender:
    def test_applies_defaults(self) -> None:
        result = renderer.render(_msg("carousel", {"items": [{"id": 1}]}))
        assert result["payload"]["auto_play"] is False
        assert result["payload"]["interval_ms"] == 3000


class TestQuickRepliesRender:
    def test_renders_options(self) -> None:
        opts = [{"label": "Yes", "value": "y"}, {"label": "No", "value": "n"}]
        result = renderer.render(_msg("quick_replies", {"options": opts}))
        assert len(result["payload"]["options"]) == 2


# ---------------------------------------------------------------------------
# Validation errors -> text fallback
# ---------------------------------------------------------------------------


class TestMissingRequiredFields:
    def test_text_missing_content(self) -> None:
        result = renderer.render(_msg("text", {}))
        assert result["type"] == "text"
        assert "render_error" in result["payload"]

    def test_product_card_missing_name(self) -> None:
        result = renderer.render(_msg("product_card", {"product_id": "p1", "price": 1}))
        assert result["type"] == "text"
        assert "render_error" in result["payload"]

    def test_order_card_missing_order_id(self) -> None:
        result = renderer.render(_msg("order_card", {"status": "shipped"}))
        assert "render_error" in result["payload"]

    def test_logistics_missing_order_id(self) -> None:
        result = renderer.render(
            _msg("logistics_timeline", {"steps": [{"status": "a", "time": "t", "location": "l"}]})
        )
        assert "render_error" in result["payload"]

    def test_confirm_missing_title(self) -> None:
        result = renderer.render(_msg("confirm", {"description": "D"}))
        assert "render_error" in result["payload"]

    def test_form_missing_fields(self) -> None:
        result = renderer.render(_msg("form", {}))
        assert "render_error" in result["payload"]

    def test_rating_missing_prompt(self) -> None:
        result = renderer.render(_msg("rating", {}))
        assert "render_error" in result["payload"]

    def test_transfer_missing_reason(self) -> None:
        result = renderer.render(_msg("transfer", {}))
        assert "render_error" in result["payload"]

    def test_carousel_missing_items(self) -> None:
        result = renderer.render(_msg("carousel", {}))
        assert "render_error" in result["payload"]

    def test_quick_replies_missing_options(self) -> None:
        result = renderer.render(_msg("quick_replies", {}))
        assert "render_error" in result["payload"]


# ---------------------------------------------------------------------------
# Specific validations
# ---------------------------------------------------------------------------


class TestSpecificValidations:
    def test_product_card_negative_price(self) -> None:
        result = renderer.render(_msg(
            "product_card", {"product_id": "p1", "name": "X", "price": -5},
        ))
        assert "render_error" in result["payload"]

    def test_product_list_length_mismatch(self) -> None:
        result = renderer.render(_msg(
            "product_list", {"products": [{"id": 1}], "total": 3},
        ))
        assert "render_error" in result["payload"]

    def test_order_card_invalid_status(self) -> None:
        result = renderer.render(_msg(
            "order_card", {"order_id": "O1", "status": "teleported"},
        ))
        assert "render_error" in result["payload"]

    def test_logistics_empty_steps(self) -> None:
        result = renderer.render(_msg(
            "logistics_timeline", {"order_id": "O1", "steps": []},
        ))
        assert "render_error" in result["payload"]

    def test_quick_replies_empty_options(self) -> None:
        result = renderer.render(_msg("quick_replies", {"options": []}))
        assert "render_error" in result["payload"]

    def test_form_invalid_field_type(self) -> None:
        fields = [{"name": "x", "type": "hologram", "label": "X", "required": False}]
        result = renderer.render(_msg("form", {"fields": fields}))
        assert "render_error" in result["payload"]


class TestUnknownType:
    def test_unknown_type_falls_back(self) -> None:
        result = renderer.render(_msg("hologram_3d", {"data": "..."}, fallback="no 3d"))
        assert result["type"] == "text"
        assert result["payload"]["render_error"] == "Unknown message type"
        assert result["payload"]["content"] == "no 3d"


class TestFallbackTextPreserved:
    def test_fallback_text_in_result(self) -> None:
        result = renderer.render(_msg("text", {"content": "hi"}, fallback="hi there"))
        assert result["fallback_text"] == "hi there"

    def test_fallback_text_on_error(self) -> None:
        result = renderer.render(_msg("text", {}, fallback="oops"))
        assert result["fallback_text"] == "oops"
