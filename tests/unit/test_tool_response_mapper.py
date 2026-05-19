"""Unit tests for ToolResponseMapper — feat-029."""
from __future__ import annotations

import pytest

from open_chat_shop.core.tool_response_mapper import ToolResponseMapper
from open_chat_shop.core.types import SessionContext, ToolResult

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ctx = SessionContext(session_id="s1", user_id="u1", channel="web")

_mapper = ToolResponseMapper()


def _ok(data: dict | None = None) -> ToolResult:
    return ToolResult(success=True, data=data)


def _fail(error: str = "something went wrong") -> ToolResult:
    return ToolResult(success=False, error=error)


# ---------------------------------------------------------------------------
# Per-tool message_type mapping (8 tools)
# ---------------------------------------------------------------------------


class TestQueryOrder:
    def test_maps_to_order_card(self) -> None:
        result = _ok({
            "order_id": "ORD-1", "status": "paid",
            "items": [{"name": "Widget"}], "total_amount": 99.0,
        })
        msg = _mapper.map("query_order", result, _ctx)
        assert msg.message_type == "order_card"

    def test_payload_fields(self) -> None:
        result = _ok({
            "order_id": "ORD-2", "status": "shipped",
            "items": [{"name": "A"}], "total_amount": 42.0,
        })
        msg = _mapper.map("query_order", result, _ctx)
        assert msg.payload["order_id"] == "ORD-2"
        assert msg.payload["status"] == "shipped"
        assert msg.payload["items"] == [{"name": "A"}]
        assert msg.payload["total_amount"] == 42.0

    def test_suggestions(self) -> None:
        msg = _mapper.map("query_order", _ok({
            "order_id": "ORD-3", "status": "delivered",
        }), _ctx)
        assert msg.suggestions == ["查看物流", "申请退款"]


class TestQueryLogistics:
    def test_maps_to_logistics_timeline(self) -> None:
        steps = [{"status": "collected", "time": "10:00", "location": "北京"}]
        result = _ok({"order_id": "ORD-4", "steps": steps})
        msg = _mapper.map("query_logistics", result, _ctx)
        assert msg.message_type == "logistics_timeline"
        assert msg.payload["steps"] == steps

    def test_payload_order_id(self) -> None:
        msg = _mapper.map("query_logistics", _ok({
            "order_id": "ORD-5", "steps": [],
        }), _ctx)
        assert msg.payload["order_id"] == "ORD-5"


class TestSearchProduct:
    def test_maps_to_product_list(self) -> None:
        products = [{"product_id": "P1", "name": "Widget", "price": 9.99}]
        result = _ok({"products": products, "total": 1})
        msg = _mapper.map("search_product", result, _ctx)
        assert msg.message_type == "product_list"
        assert msg.payload["products"] == products
        assert msg.payload["total"] == 1

    def test_suggestions(self) -> None:
        msg = _mapper.map("search_product", _ok({
            "products": [], "total": 0,
        }), _ctx)
        assert msg.suggestions == ["查看详情", "加入购物车"]


class TestCheckRefundEligibility:
    def test_maps_to_text_eligible(self) -> None:
        msg = _mapper.map("check_refund_eligibility", _ok({
            "order_id": "ORD-6", "eligible": True,
        }), _ctx)
        assert msg.message_type == "text"
        assert "符合退款" in msg.payload["content"]

    def test_maps_to_text_not_eligible(self) -> None:
        msg = _mapper.map("check_refund_eligibility", _ok({
            "order_id": "ORD-7", "eligible": False, "reason": "已超过退款期限",
        }), _ctx)
        assert "暂不支持退款" in msg.payload["content"]
        assert "已超过退款期限" in msg.payload["content"]


class TestCreateRefund:
    def test_maps_to_text(self) -> None:
        msg = _mapper.map("create_refund", _ok({
            "refund_id": "REF-1", "order_id": "ORD-8", "amount": 50.0, "status": "pending",
        }), _ctx)
        assert msg.message_type == "text"
        assert "REF-1" in msg.payload["content"]
        assert "50.0" in msg.payload["content"]


class TestCancelOrder:
    def test_maps_to_text(self) -> None:
        msg = _mapper.map("cancel_order", _ok({
            "order_id": "ORD-9", "status": "cancelled",
        }), _ctx)
        assert msg.message_type == "text"
        assert "ORD-9" in msg.payload["content"]

    def test_suggestions(self) -> None:
        msg = _mapper.map("cancel_order", _ok({
            "order_id": "ORD-9", "status": "cancelled",
        }), _ctx)
        assert msg.suggestions == ["重新下单"]


class TestModifyAddress:
    def test_maps_to_text(self) -> None:
        msg = _mapper.map("modify_address", _ok({
            "order_id": "ORD-10", "new_address": "北京市朝阳区",
        }), _ctx)
        assert msg.message_type == "text"
        assert "ORD-10" in msg.payload["content"]


class TestHandoffToHuman:
    def test_maps_to_transfer(self) -> None:
        msg = _mapper.map("handoff_to_human", _ok({
            "department": "售后", "reason": "客户要求",
        }), _ctx)
        assert msg.message_type == "transfer"
        assert msg.payload["department"] == "售后"
        assert msg.payload["reason"] == "客户要求"

    def test_default_wait(self) -> None:
        msg = _mapper.map("handoff_to_human", _ok({
            "department": "客服", "reason": "投诉",
        }), _ctx)
        assert msg.payload["estimated_wait_seconds"] == 60


# ---------------------------------------------------------------------------
# Error / edge cases
# ---------------------------------------------------------------------------


class TestFailedResult:
    def test_returns_text_with_error(self) -> None:
        msg = _mapper.map("query_order", _fail("订单不存在"), _ctx)
        assert msg.message_type == "text"
        assert "订单不存在" in msg.payload["content"]


class TestNullData:
    def test_returns_text_generic_success(self) -> None:
        msg = _mapper.map("query_order", _ok(None), _ctx)
        assert msg.message_type == "text"
        assert "操作成功" in msg.payload["content"]


class TestUnknownTool:
    def test_returns_text_fallback(self) -> None:
        msg = _mapper.map("some_new_tool", _ok({"key": "value"}), _ctx)
        assert msg.message_type == "text"
        assert "key" in msg.payload["content"]
