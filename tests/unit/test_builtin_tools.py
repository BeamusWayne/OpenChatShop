"""Unit tests for built-in e-commerce tools.

Covers: instantiation, validate(), execute(), pre_check(), and
the security matrix (requires_confirmation) for all 8 tools.
"""

from __future__ import annotations

import copy

import pytest

from open_chat_shop.core.types import SessionContext, ToolResult
from open_chat_shop.tools.builtin import (
    ALL_TOOLS,
    CancelOrderTool,
    CheckRefundEligibilityTool,
    CreateRefundTool,
    HandoffToHumanTool,
    ModifyAddressTool,
    QueryLogisticsTool,
    QueryOrderTool,
    SearchProductTool,
    _mock_data,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ctx() -> SessionContext:
    """Minimal SessionContext for testing."""
    return SessionContext(
        session_id="test-session",
        user_id="user-001",
        channel="web",
        user_role="customer",
    )


@pytest.fixture(autouse=True)
def _preserve_mock_data():
    """Ensure mock data is restored after each test to prevent mutation leaks."""
    original_orders = copy.deepcopy(_mock_data.ORDERS)
    original_refunds = copy.deepcopy(_mock_data.REFUNDS)
    original_counter = _mock_data.REFUND_COUNTER
    yield
    _mock_data.ORDERS.clear()
    _mock_data.ORDERS.update(original_orders)
    _mock_data.REFUNDS.clear()
    _mock_data.REFUNDS.update(original_refunds)
    _mock_data.REFUND_COUNTER = original_counter


# ---------------------------------------------------------------------------
# 1. Instantiation tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_cls", ALL_TOOLS, ids=lambda cls: cls.__name__)
def test_tool_can_be_instantiated(tool_cls: type):
    tool = tool_cls()
    assert tool.name
    assert tool.description
    assert tool.category
    assert isinstance(tool.params_schema, dict)
    assert tool.permissions is not None


# ---------------------------------------------------------------------------
# 2. validate() tests -- accept correct, reject invalid
# ---------------------------------------------------------------------------

class TestQueryOrderValidation:
    def test_valid(self):
        result = QueryOrderTool().validate({"order_id": "ORD-001"})
        assert result.valid is True

    def test_missing_order_id(self):
        result = QueryOrderTool().validate({})
        assert result.valid is False
        assert result.errors

    def test_extra_field_rejected(self):
        result = QueryOrderTool().validate({"order_id": "ORD-001", "extra": "bad"})
        assert result.valid is False


class TestSearchProductValidation:
    def test_valid_minimal(self):
        result = SearchProductTool().validate({"keyword": "mouse"})
        assert result.valid is True

    def test_valid_full(self):
        result = SearchProductTool().validate(
            {"keyword": "mouse", "category": "electronics", "limit": 3}
        )
        assert result.valid is True

    def test_missing_keyword(self):
        result = SearchProductTool().validate({"category": "electronics"})
        assert result.valid is False


class TestCreateRefundValidation:
    def test_valid_minimal(self):
        result = CreateRefundTool().validate({"order_id": "ORD-001", "reason": "defective"})
        assert result.valid is True

    def test_valid_with_amount(self):
        result = CreateRefundTool().validate(
            {"order_id": "ORD-001", "reason": "defective", "amount": 100.0}
        )
        assert result.valid is True

    def test_missing_reason(self):
        result = CreateRefundTool().validate({"order_id": "ORD-001"})
        assert result.valid is False


class TestHandoffToHumanValidation:
    def test_valid_empty(self):
        result = HandoffToHumanTool().validate({})
        assert result.valid is True

    def test_valid_with_reason(self):
        result = HandoffToHumanTool().validate({"reason": "complex issue"})
        assert result.valid is True


class TestCancelOrderValidation:
    def test_valid(self):
        result = CancelOrderTool().validate({"order_id": "ORD-002", "reason": "changed mind"})
        assert result.valid is True

    def test_missing_reason(self):
        result = CancelOrderTool().validate({"order_id": "ORD-002"})
        assert result.valid is False


class TestModifyAddressValidation:
    def test_valid_minimal(self):
        result = ModifyAddressTool().validate({"order_id": "ORD-002", "address": "999 New St"})
        assert result.valid is True

    def test_valid_with_phone(self):
        result = ModifyAddressTool().validate(
            {"order_id": "ORD-002", "address": "999 New St", "phone": "13100131000"}
        )
        assert result.valid is True

    def test_missing_address(self):
        result = ModifyAddressTool().validate({"order_id": "ORD-002"})
        assert result.valid is False


class TestQueryLogisticsValidation:
    def test_valid(self):
        result = QueryLogisticsTool().validate({"order_id": "ORD-001"})
        assert result.valid is True

    def test_missing_order_id(self):
        result = QueryLogisticsTool().validate({})
        assert result.valid is False


class TestCheckRefundEligibilityValidation:
    def test_valid(self):
        result = CheckRefundEligibilityTool().validate({"order_id": "ORD-001"})
        assert result.valid is True

    def test_missing_order_id(self):
        result = CheckRefundEligibilityTool().validate({})
        assert result.valid is False


# ---------------------------------------------------------------------------
# 3. execute() tests
# ---------------------------------------------------------------------------

class TestQueryOrderExecute:
    @pytest.mark.asyncio
    async def test_existing_order(self, ctx: SessionContext):
        result = await QueryOrderTool().execute({"order_id": "ORD-001"}, ctx)
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data["order_id"] == "ORD-001"
        assert result.data["status"] == "shipped"
        assert len(result.data["items"]) == 2
        assert result.data["total_amount"] == 228.00

    @pytest.mark.asyncio
    async def test_nonexistent_order(self, ctx: SessionContext):
        result = await QueryOrderTool().execute({"order_id": "ORD-999"}, ctx)
        assert result.success is False
        assert "未找到" in result.error


class TestQueryLogisticsExecute:
    @pytest.mark.asyncio
    async def test_order_with_logistics(self, ctx: SessionContext):
        result = await QueryLogisticsTool().execute({"order_id": "ORD-001"}, ctx)
        assert result.success is True
        assert result.data["carrier"] == "顺丰速运"
        assert result.data["tracking_number"] == "SF1234567890"
        assert len(result.data["timeline"]) >= 1

    @pytest.mark.asyncio
    async def test_order_without_logistics(self, ctx: SessionContext):
        result = await QueryLogisticsTool().execute({"order_id": "ORD-002"}, ctx)
        assert result.success is False
        assert "暂无物流" in result.error

    @pytest.mark.asyncio
    async def test_nonexistent_order(self, ctx: SessionContext):
        result = await QueryLogisticsTool().execute({"order_id": "ORD-999"}, ctx)
        assert result.success is False


class TestSearchProductExecute:
    @pytest.mark.asyncio
    async def test_search_by_keyword(self, ctx: SessionContext):
        result = await SearchProductTool().execute({"keyword": "鼠标"}, ctx)
        assert result.success is True
        assert result.data["total_found"] >= 1
        assert any("鼠标" in p["name"] for p in result.data["products"])

    @pytest.mark.asyncio
    async def test_search_with_category(self, ctx: SessionContext):
        result = await SearchProductTool().execute({"keyword": "desk", "category": "office"}, ctx)
        assert result.success is True
        assert all(p["name"] for p in result.data["products"])

    @pytest.mark.asyncio
    async def test_search_with_limit(self, ctx: SessionContext):
        result = await SearchProductTool().execute({"keyword": "e", "limit": 2}, ctx)
        assert result.success is True
        assert len(result.data["products"]) <= 2

    @pytest.mark.asyncio
    async def test_search_no_results(self, ctx: SessionContext):
        result = await SearchProductTool().execute({"keyword": "zzznonexistent"}, ctx)
        assert result.success is True
        assert result.data["total_found"] == 0


class TestCheckRefundEligibilityExecute:
    @pytest.mark.asyncio
    async def test_eligible_order(self, ctx: SessionContext):
        result = await CheckRefundEligibilityTool().execute({"order_id": "ORD-001"}, ctx)
        assert result.success is True
        assert result.data["eligible"] is True
        assert result.data["deadline"] is not None

    @pytest.mark.asyncio
    async def test_already_refunded(self, ctx: SessionContext):
        result = await CheckRefundEligibilityTool().execute({"order_id": "ORD-004"}, ctx)
        assert result.success is True
        assert result.data["eligible"] is False

    @pytest.mark.asyncio
    async def test_nonexistent(self, ctx: SessionContext):
        result = await CheckRefundEligibilityTool().execute({"order_id": "ORD-999"}, ctx)
        assert result.success is False


class TestCreateRefundExecute:
    @pytest.mark.asyncio
    async def test_create_refund_success(self, ctx: SessionContext):
        tool = CreateRefundTool()
        result = await tool.execute({"order_id": "ORD-001", "reason": "defective item"}, ctx)
        assert result.success is True
        assert result.data["refund_id"].startswith("REF-")
        assert result.data["status"] == "processing"
        assert result.data["amount"] == 228.00

    @pytest.mark.asyncio
    async def test_create_refund_custom_amount(self, ctx: SessionContext):
        tool = CreateRefundTool()
        result = await tool.execute(
            {"order_id": "ORD-002", "reason": "partial issue", "amount": 50.0}, ctx
        )
        assert result.success is True
        assert result.data["amount"] == 50.0

    @pytest.mark.asyncio
    async def test_create_refund_nonexistent_order(self, ctx: SessionContext):
        result = await CreateRefundTool().execute({"order_id": "ORD-999", "reason": "x"}, ctx)
        assert result.success is False


class TestCancelOrderExecute:
    @pytest.mark.asyncio
    async def test_cancel_pending_order(self, ctx: SessionContext):
        tool = CancelOrderTool()
        result = await tool.execute({"order_id": "ORD-002", "reason": "changed mind"}, ctx)
        assert result.success is True
        assert result.data["status"] == "cancelled"
        assert _mock_data.ORDERS["ORD-002"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_processing_order(self, ctx: SessionContext):
        result = await CancelOrderTool().execute({"order_id": "ORD-003", "reason": "urgent"}, ctx)
        assert result.success is True
        assert result.data["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_shipped_order_fails(self, ctx: SessionContext):
        result = await CancelOrderTool().execute({"order_id": "ORD-001", "reason": "too late"}, ctx)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, ctx: SessionContext):
        result = await CancelOrderTool().execute({"order_id": "ORD-999", "reason": "x"}, ctx)
        assert result.success is False


class TestModifyAddressExecute:
    @pytest.mark.asyncio
    async def test_modify_pending_order(self, ctx: SessionContext):
        tool = ModifyAddressTool()
        result = await tool.execute(
            {"order_id": "ORD-002", "address": "999 New St, Hangzhou", "phone": "15000150000"},
            ctx,
        )
        assert result.success is True
        assert result.data["new_address"] == "999 New St, Hangzhou"
        assert _mock_data.ORDERS["ORD-002"]["address"] == "999 New St, Hangzhou"
        assert _mock_data.ORDERS["ORD-002"]["phone"] == "15000150000"

    @pytest.mark.asyncio
    async def test_modify_without_phone(self, ctx: SessionContext):
        result = await ModifyAddressTool().execute(
            {"order_id": "ORD-002", "address": "888 Another St"},
            ctx,
        )
        assert result.success is True
        assert result.data["new_address"] == "888 Another St"

    @pytest.mark.asyncio
    async def test_modify_shipped_order_fails(self, ctx: SessionContext):
        result = await ModifyAddressTool().execute(
            {"order_id": "ORD-001", "address": "000 Impossible St"},
            ctx,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_modify_nonexistent_order(self, ctx: SessionContext):
        result = await ModifyAddressTool().execute(
            {"order_id": "ORD-999", "address": "000 Nowhere"},
            ctx,
        )
        assert result.success is False


class TestHandoffToHumanExecute:
    @pytest.mark.asyncio
    async def test_handoff_without_reason(self, ctx: SessionContext):
        result = await HandoffToHumanTool().execute({}, ctx)
        assert result.success is True
        assert result.data["transferred"] is True
        assert result.data["estimated_wait_seconds"] > 0

    @pytest.mark.asyncio
    async def test_handoff_with_reason(self, ctx: SessionContext):
        result = await HandoffToHumanTool().execute({"reason": "complex dispute"}, ctx)
        assert result.success is True
        assert result.data["reason"] == "complex dispute"


# ---------------------------------------------------------------------------
# 4. pre_check() tests
# ---------------------------------------------------------------------------

class TestCheckRefundEligibilityPreCheck:
    @pytest.mark.asyncio
    async def test_passes_for_normal_order(self, ctx: SessionContext):
        tool = CheckRefundEligibilityTool()
        result = await tool.pre_check({"order_id": "ORD-001"}, ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_for_nonexistent_order(self, ctx: SessionContext):
        tool = CheckRefundEligibilityTool()
        result = await tool.pre_check({"order_id": "ORD-999"}, ctx)
        assert result.passed is False
        assert "不存在" in result.reason

    @pytest.mark.asyncio
    async def test_fails_for_already_refunded(self, ctx: SessionContext):
        tool = CheckRefundEligibilityTool()
        result = await tool.pre_check({"order_id": "ORD-004"}, ctx)
        assert result.passed is False
        assert "已退款" in result.reason


class TestCreateRefundPreCheck:
    @pytest.mark.asyncio
    async def test_passes_for_normal_order(self, ctx: SessionContext):
        tool = CreateRefundTool()
        result = await tool.pre_check({"order_id": "ORD-001", "reason": "x"}, ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_for_refunded_order(self, ctx: SessionContext):
        tool = CreateRefundTool()
        result = await tool.pre_check({"order_id": "ORD-004", "reason": "x"}, ctx)
        assert result.passed is False


class TestCancelOrderPreCheck:
    @pytest.mark.asyncio
    async def test_passes_for_pending(self, ctx: SessionContext):
        tool = CancelOrderTool()
        result = await tool.pre_check({"order_id": "ORD-002", "reason": "x"}, ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_passes_for_processing(self, ctx: SessionContext):
        tool = CancelOrderTool()
        result = await tool.pre_check({"order_id": "ORD-003", "reason": "x"}, ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_for_shipped(self, ctx: SessionContext):
        tool = CancelOrderTool()
        result = await tool.pre_check({"order_id": "ORD-001", "reason": "x"}, ctx)
        assert result.passed is False
        assert "不可取消" in result.reason

    @pytest.mark.asyncio
    async def test_fails_for_nonexistent(self, ctx: SessionContext):
        tool = CancelOrderTool()
        result = await tool.pre_check({"order_id": "ORD-999", "reason": "x"}, ctx)
        assert result.passed is False


class TestModifyAddressPreCheck:
    @pytest.mark.asyncio
    async def test_passes_for_pending(self, ctx: SessionContext):
        tool = ModifyAddressTool()
        result = await tool.pre_check({"order_id": "ORD-002", "address": "x"}, ctx)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_fails_for_shipped(self, ctx: SessionContext):
        tool = ModifyAddressTool()
        result = await tool.pre_check({"order_id": "ORD-001", "address": "x"}, ctx)
        assert result.passed is False
        assert "已发货" in result.reason

    @pytest.mark.asyncio
    async def test_fails_for_delivered(self, ctx: SessionContext):
        tool = ModifyAddressTool()
        result = await tool.pre_check({"order_id": "ORD-005", "address": "x"}, ctx)
        assert result.passed is False


# ---------------------------------------------------------------------------
# 5. Security matrix: requires_confirmation
# ---------------------------------------------------------------------------

class TestSecurityMatrix:
    """Verify that tools which require confirmation have the flag set,
    and read-only tools do not."""

    def test_query_order_no_confirmation(self):
        assert QueryOrderTool().permissions.requires_confirmation is False

    def test_query_logistics_no_confirmation(self):
        assert QueryLogisticsTool().permissions.requires_confirmation is False

    def test_search_product_no_confirmation(self):
        assert SearchProductTool().permissions.requires_confirmation is False

    def test_check_refund_eligibility_no_confirmation(self):
        assert CheckRefundEligibilityTool().permissions.requires_confirmation is False

    def test_create_refund_requires_confirmation(self):
        tool = CreateRefundTool()
        assert tool.permissions.requires_confirmation is True
        assert tool.permissions.confirmation_threshold is not None
        assert tool.permissions.confirmation_threshold["field"] == "amount"
        assert tool.permissions.confirmation_threshold["gt"] == 500

    def test_cancel_order_requires_confirmation(self):
        assert CancelOrderTool().permissions.requires_confirmation is True

    def test_modify_address_requires_confirmation(self):
        assert ModifyAddressTool().permissions.requires_confirmation is True

    def test_handoff_no_confirmation(self):
        assert HandoffToHumanTool().permissions.requires_confirmation is False

    def test_all_tools_have_required_roles(self):
        for tool_cls in ALL_TOOLS:
            tool = tool_cls()
            assert "customer" in tool.permissions.required_roles, (
                f"{tool.name} missing 'customer' in required_roles"
            )

    def test_idempotent_tools(self):
        idempotent_tools = [
            QueryOrderTool, QueryLogisticsTool, SearchProductTool,
            CheckRefundEligibilityTool, HandoffToHumanTool,
        ]
        for tool_cls in idempotent_tools:
            assert tool_cls().permissions.idempotent is True, (
                f"{tool_cls.__name__} should be idempotent"
            )

    def test_non_idempotent_tools(self):
        non_idempotent = [CreateRefundTool, CancelOrderTool, ModifyAddressTool]
        for tool_cls in non_idempotent:
            assert tool_cls().permissions.idempotent is False, (
                f"{tool_cls.__name__} should not be idempotent"
            )


# ---------------------------------------------------------------------------
# 6. compensate() tests
# ---------------------------------------------------------------------------

class TestCompensate:
    @pytest.mark.asyncio
    async def test_cancel_order_compensate_restores_state(self, ctx: SessionContext):
        tool = CancelOrderTool()
        original_status = _mock_data.ORDERS["ORD-002"]["status"]
        await tool.execute({"order_id": "ORD-002", "reason": "test"}, ctx)
        assert _mock_data.ORDERS["ORD-002"]["status"] == "cancelled"

        await tool.compensate({"order_id": "ORD-002", "reason": "test"}, ctx)
        assert _mock_data.ORDERS["ORD-002"]["status"] == original_status

    @pytest.mark.asyncio
    async def test_modify_address_compensate_restores_state(self, ctx: SessionContext):
        tool = ModifyAddressTool()
        original_address = _mock_data.ORDERS["ORD-002"]["address"]
        await tool.execute({"order_id": "ORD-002", "address": "Restored St"}, ctx)
        assert _mock_data.ORDERS["ORD-002"]["address"] == "Restored St"

        await tool.compensate({"order_id": "ORD-002", "address": "Restored St"}, ctx)
        assert _mock_data.ORDERS["ORD-002"]["address"] == original_address

    @pytest.mark.asyncio
    async def test_create_refund_compensate_removes_record(self, ctx: SessionContext):
        tool = CreateRefundTool()
        result = await tool.execute({"order_id": "ORD-002", "reason": "test"}, ctx)
        refund_id = result.data["refund_id"]
        assert refund_id in _mock_data.REFUNDS

        await tool.compensate({"order_id": "ORD-002", "reason": "test"}, ctx)
        assert refund_id not in _mock_data.REFUNDS


class TestOrderOwnershipIDOR:
    """Regression for the IDOR/BOLA fix (audit CRITICAL-1).

    Seeded orders are owned by ``user-001``. Order tools reach them via
    OrderRepository.get_for_user, so an authenticated user must not read or
    mutate another user's order by guessing its ID. A non-owned order is
    reported as 'not found' — no enumeration oracle, no mutation.
    """

    @pytest.fixture()
    def attacker(self) -> SessionContext:
        return SessionContext(
            session_id="attacker-session",
            user_id="user-999",  # owns none of the seeded orders
            channel="web",
            user_role="customer",
        )

    @pytest.mark.asyncio
    async def test_query_order_denies_other_users_order(self, attacker: SessionContext):
        result = await QueryOrderTool().execute({"order_id": "ORD-001"}, attacker)
        assert result.success is False
        assert "ORD-001" in result.error  # surfaced as not-found, leaks nothing

    @pytest.mark.asyncio
    async def test_query_logistics_denies_other_users_order(self, attacker: SessionContext):
        result = await QueryLogisticsTool().execute({"order_id": "ORD-001"}, attacker)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_cancel_order_denies_and_does_not_mutate(self, attacker: SessionContext):
        result = await CancelOrderTool().execute(
            {"order_id": "ORD-002", "reason": "malicious"}, attacker
        )
        assert result.success is False
        assert _mock_data.ORDERS["ORD-002"]["status"] == "pending"  # untouched

    @pytest.mark.asyncio
    async def test_create_refund_denies_other_users_order(self, attacker: SessionContext):
        result = await CreateRefundTool().execute(
            {"order_id": "ORD-001", "reason": "malicious"}, attacker
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_modify_address_denies_and_does_not_mutate(self, attacker: SessionContext):
        before = _mock_data.ORDERS["ORD-001"]["address"]
        result = await ModifyAddressTool().execute(
            {"order_id": "ORD-001", "address": "attacker-controlled address"}, attacker
        )
        assert result.success is False
        assert _mock_data.ORDERS["ORD-001"]["address"] == before  # untouched

    @pytest.mark.asyncio
    async def test_legitimate_owner_is_unaffected(self, ctx: SessionContext):
        # Sanity: the real owner (user-001) still succeeds — no false positives.
        result = await QueryOrderTool().execute({"order_id": "ORD-001"}, ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_identity_falls_back_to_advisory(self) -> None:
        # When no identity is established (user_id=None, e.g. auth disabled),
        # ownership is not enforced so the local/dev demo keeps working.
        anon = SessionContext(
            session_id="anon", user_id=None, channel="web", user_role="customer"
        )
        result = await QueryOrderTool().execute({"order_id": "ORD-001"}, anon)
        assert result.success is True
