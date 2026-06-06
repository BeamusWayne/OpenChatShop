"""Re-audit regression tests for the order-mutation tool scaffold (OPT cluster).

The audit asked to extract the duplicated ``get_for_user -> status guard ->
mutate -> compensate`` scaffold shared by cancel_order, modify_address and
create_refund into a reusable template (:class:`OrderMutationTool`), WITHOUT
changing behaviour.

These tests pin the refactor's contract so a future change cannot silently
regress it:

* the three mutation tools share the extracted base class (the scaffold lives
  in exactly one place now);
* ownership enforcement (IDOR/BOLA, audit CRITICAL-1) still holds on both the
  ``pre_check`` and ``execute`` seams the base defines;
* the status guards still reject with the exact original messages, in both
  Chinese (pre_check) and English (execute);
* compensation still restores the prior state / removes the created record.

They exercise the REAL tools against the in-memory repositories (not mocks),
because the scaffold's correctness is the interaction between tool, base class
and repository — the seam the last parallel round got wrong by trusting
isolated mocks.
"""

from __future__ import annotations

import copy
from unittest.mock import patch

import pytest

from open_chat_shop.core.types import SessionContext
from open_chat_shop.tools.builtin import (
    CancelOrderTool,
    CheckRefundEligibilityTool,
    CreateRefundTool,
    ModifyAddressTool,
    _mock_data,
)
from open_chat_shop.tools.builtin._order_mutation import OrderMutationTool


@pytest.fixture(autouse=True)
def _preserve_mock_data():
    """Restore mutable mock data after each test (mirrors the suite fixture)."""
    original_orders = copy.deepcopy(_mock_data.ORDERS)
    original_refunds = copy.deepcopy(_mock_data.REFUNDS)
    original_counter = _mock_data.REFUND_COUNTER
    yield
    _mock_data.ORDERS.clear()
    _mock_data.ORDERS.update(original_orders)
    _mock_data.REFUNDS.clear()
    _mock_data.REFUNDS.update(original_refunds)
    _mock_data.REFUND_COUNTER = original_counter


@pytest.fixture()
def owner() -> SessionContext:
    """The real owner of every seeded order (customer_id == user-001)."""
    return SessionContext(
        session_id="owner-session",
        user_id="user-001",
        channel="web",
        user_role="customer",
    )


@pytest.fixture()
def attacker() -> SessionContext:
    """A user who owns none of the seeded orders."""
    return SessionContext(
        session_id="attacker-session",
        user_id="user-999",
        channel="web",
        user_role="customer",
    )


# ---------------------------------------------------------------------------
# 1. The scaffold is actually shared (the point of the refactor)
# ---------------------------------------------------------------------------

class TestSharedScaffold:
    @pytest.mark.parametrize(
        "tool_cls", [CancelOrderTool, ModifyAddressTool, CreateRefundTool]
    )
    def test_mutation_tools_use_shared_base(self, tool_cls: type) -> None:
        assert issubclass(tool_cls, OrderMutationTool)

    def test_read_only_tool_is_not_a_mutation_tool(self) -> None:
        # check_refund_eligibility computes a deadline and mutates nothing — it
        # must NOT be pulled into the mutation scaffold.
        assert not issubclass(CheckRefundEligibilityTool, OrderMutationTool)

    @pytest.mark.parametrize(
        "tool_cls", [CancelOrderTool, ModifyAddressTool, CreateRefundTool]
    )
    def test_pre_check_and_execute_defined_on_base_only(self, tool_cls: type) -> None:
        # The scaffold (pre_check/execute) must live on the base, not be
        # re-implemented per tool — that duplication is exactly what was removed.
        assert "pre_check" not in tool_cls.__dict__
        assert "execute" not in tool_cls.__dict__
        assert "pre_check" in OrderMutationTool.__dict__
        assert "execute" in OrderMutationTool.__dict__


# ---------------------------------------------------------------------------
# 2. Ownership enforcement on BOTH seams the base defines (IDOR/BOLA)
# ---------------------------------------------------------------------------

class TestOwnershipStillEnforced:
    @pytest.mark.asyncio
    async def test_cancel_pre_check_denies_other_user(self, attacker: SessionContext) -> None:
        # pre_check must report a non-owned order as "not found", never leak it.
        result = await CancelOrderTool().pre_check(
            {"order_id": "ORD-002", "reason": "x"}, attacker
        )
        assert result.passed is False
        assert "不存在" in (result.reason or "")

    @pytest.mark.asyncio
    async def test_modify_pre_check_denies_other_user(self, attacker: SessionContext) -> None:
        result = await ModifyAddressTool().pre_check(
            {"order_id": "ORD-002", "address": "x"}, attacker
        )
        assert result.passed is False
        assert "不存在" in (result.reason or "")

    @pytest.mark.asyncio
    async def test_create_refund_pre_check_denies_other_user(
        self, attacker: SessionContext
    ) -> None:
        result = await CreateRefundTool().pre_check(
            {"order_id": "ORD-001", "reason": "x"}, attacker
        )
        assert result.passed is False
        assert "不存在" in (result.reason or "")

    @pytest.mark.asyncio
    async def test_cancel_execute_denies_and_does_not_mutate(
        self, attacker: SessionContext
    ) -> None:
        result = await CancelOrderTool().execute(
            {"order_id": "ORD-002", "reason": "malicious"}, attacker
        )
        assert result.success is False
        assert "ORD-002" in (result.error or "")
        assert _mock_data.ORDERS["ORD-002"]["status"] == "pending"  # untouched

    @pytest.mark.asyncio
    async def test_modify_execute_denies_and_does_not_mutate(
        self, attacker: SessionContext
    ) -> None:
        before = _mock_data.ORDERS["ORD-002"]["address"]
        result = await ModifyAddressTool().execute(
            {"order_id": "ORD-002", "address": "attacker-controlled"}, attacker
        )
        assert result.success is False
        assert _mock_data.ORDERS["ORD-002"]["address"] == before

    @pytest.mark.asyncio
    async def test_create_refund_execute_denies_and_creates_nothing(
        self, attacker: SessionContext
    ) -> None:
        before = dict(_mock_data.REFUNDS)
        result = await CreateRefundTool().execute(
            {"order_id": "ORD-001", "reason": "malicious"}, attacker
        )
        assert result.success is False
        assert before == _mock_data.REFUNDS  # no refund record created


# ---------------------------------------------------------------------------
# 3. Status guards keep the exact original messages on both seams
# ---------------------------------------------------------------------------

class TestStatusGuardMessagesUnchanged:
    @pytest.mark.asyncio
    async def test_cancel_shipped_messages(self, owner: SessionContext) -> None:
        params = {"order_id": "ORD-001", "reason": "too late"}  # ORD-001 is shipped
        check = await CancelOrderTool().pre_check(params, owner)
        assert check.passed is False
        assert check.reason == "订单 ORD-001 当前状态不可取消"

        result = await CancelOrderTool().execute(params, owner)
        assert result.success is False
        assert result.error == "Order ORD-001 cannot be cancelled (status: shipped)"

    @pytest.mark.asyncio
    async def test_modify_shipped_messages(self, owner: SessionContext) -> None:
        params = {"order_id": "ORD-001", "address": "nope"}  # ORD-001 is shipped
        check = await ModifyAddressTool().pre_check(params, owner)
        assert check.passed is False
        assert check.reason == "订单 ORD-001 已发货，无法修改地址"

        result = await ModifyAddressTool().execute(params, owner)
        assert result.success is False
        assert result.error == (
            "Cannot modify address: order ORD-001 has shipped (status: shipped)"
        )

    @pytest.mark.asyncio
    async def test_create_refund_refunded_pre_check_blocks_execute_does_not(
        self, owner: SessionContext
    ) -> None:
        # Faithful to the original: pre_check rejects a refunded order (zh), but
        # execute historically did NOT re-guard status — it would proceed.
        params = {"order_id": "ORD-004", "reason": "x"}  # ORD-004 is refunded
        check = await CreateRefundTool().pre_check(params, owner)
        assert check.passed is False
        assert check.reason == "订单 ORD-004 已退款"

        result = await CreateRefundTool().execute(params, owner)
        assert result.success is True  # execute does not re-check the refunded status
        assert result.data is not None
        assert result.data["status"] == "processing"

    @pytest.mark.asyncio
    async def test_not_found_messages_uniform(self, owner: SessionContext) -> None:
        # Missing order: zh on pre_check, en on execute, for every mutation tool.
        for tool, extra in (
            (CancelOrderTool(), {"reason": "x"}),
            (ModifyAddressTool(), {"address": "x"}),
            (CreateRefundTool(), {"reason": "x"}),
        ):
            params = {"order_id": "ORD-404", **extra}
            check = await tool.pre_check(params, owner)
            assert check.reason == "订单 ORD-404 不存在"
            result = await tool.execute(params, owner)
            assert result.error == "Order ORD-404 not found"


# ---------------------------------------------------------------------------
# 4. Compensation still rolls back (the scaffold's safety net)
# ---------------------------------------------------------------------------

class TestCompensationStillWorks:
    @pytest.mark.asyncio
    async def test_cancel_compensate_restores_status(self, owner: SessionContext) -> None:
        tool = CancelOrderTool()
        original = _mock_data.ORDERS["ORD-002"]["status"]
        await tool.execute({"order_id": "ORD-002", "reason": "x"}, owner)
        assert _mock_data.ORDERS["ORD-002"]["status"] == "cancelled"
        await tool.compensate({"order_id": "ORD-002", "reason": "x"}, owner)
        assert _mock_data.ORDERS["ORD-002"]["status"] == original

    @pytest.mark.asyncio
    async def test_modify_compensate_restores_address(self, owner: SessionContext) -> None:
        tool = ModifyAddressTool()
        original = _mock_data.ORDERS["ORD-002"]["address"]
        await tool.execute({"order_id": "ORD-002", "address": "Temp St"}, owner)
        assert _mock_data.ORDERS["ORD-002"]["address"] == "Temp St"
        await tool.compensate({"order_id": "ORD-002", "address": "Temp St"}, owner)
        assert _mock_data.ORDERS["ORD-002"]["address"] == original

    @pytest.mark.asyncio
    async def test_create_refund_compensate_removes_record(
        self, owner: SessionContext
    ) -> None:
        tool = CreateRefundTool()
        result = await tool.execute({"order_id": "ORD-002", "reason": "x"}, owner)
        assert result.data is not None
        refund_id = result.data["refund_id"]
        assert refund_id in _mock_data.REFUNDS
        await tool.compensate({"order_id": "ORD-002", "reason": "x"}, owner)
        assert refund_id not in _mock_data.REFUNDS


# ---------------------------------------------------------------------------
# 5. The happy-path mutation payloads are unchanged
# ---------------------------------------------------------------------------

class TestHappyPathPayloadsUnchanged:
    @pytest.mark.asyncio
    async def test_cancel_success_payload(self, owner: SessionContext) -> None:
        result = await CancelOrderTool().execute(
            {"order_id": "ORD-002", "reason": "changed mind"}, owner
        )
        assert result.success is True
        assert result.data == {
            "order_id": "ORD-002",
            "status": "cancelled",
            "reason": "changed mind",
        }
        assert _mock_data.ORDERS["ORD-002"]["status"] == "cancelled"
        assert _mock_data.ORDERS["ORD-002"]["cancellation_reason"] == "changed mind"

    @pytest.mark.asyncio
    async def test_modify_success_payload(self, owner: SessionContext) -> None:
        before = _mock_data.ORDERS["ORD-002"]["address"]
        result = await ModifyAddressTool().execute(
            {"order_id": "ORD-002", "address": "777 Final Rd", "phone": "13900139000"},
            owner,
        )
        assert result.success is True
        assert result.data is not None
        assert result.data["new_address"] == "777 Final Rd"
        assert result.data["old_address"] == before
        assert _mock_data.ORDERS["ORD-002"]["address"] == "777 Final Rd"
        assert _mock_data.ORDERS["ORD-002"]["phone"] == "13900139000"

    @pytest.mark.asyncio
    async def test_create_refund_default_amount_payload(self, owner: SessionContext) -> None:
        result = await CreateRefundTool().execute(
            {"order_id": "ORD-001", "reason": "defective"}, owner
        )
        assert result.success is True
        assert result.data is not None
        assert result.data["refund_id"].startswith("REF-")
        assert result.data["status"] == "processing"
        assert result.data["amount"] == _mock_data.ORDERS["ORD-001"]["total_amount"]


# ---------------------------------------------------------------------------
# 6. execute reuses the order pre_check fetched (one ownership query / mutation)
# ---------------------------------------------------------------------------

class TestExecuteReusesPreCheckedOrder:
    @pytest.mark.asyncio
    async def test_pre_check_then_execute_queries_once(
        self, owner: SessionContext
    ) -> None:
        """A mutation that pre_checks then executes must hit the repo ONCE.

        Pre-fix execute() re-ran get_for_user, so the ownership lookup + status
        guard ran twice back-to-back for every mutation. pre_check now stashes
        the owned order on the request context and execute reuses it.
        """
        tool = CancelOrderTool()
        params = {"order_id": "ORD-002", "reason": "changed mind"}

        with patch.object(
            tool._order_repo,
            "get_for_user",
            wraps=tool._order_repo.get_for_user,
        ) as spy:
            check = await tool.pre_check(params, owner)
            assert check.passed is True
            result = await tool.execute(params, owner)

        assert result.success is True
        assert result.data == {
            "order_id": "ORD-002",
            "status": "cancelled",
            "reason": "changed mind",
        }
        assert spy.call_count == 1  # pre-fix: 2 (pre_check + execute each fetched)
        # The transient stash must not linger on the context after execute.
        assert "_mutation_order" not in owner.slots

    @pytest.mark.asyncio
    async def test_standalone_execute_still_fetches_and_works(
        self, owner: SessionContext
    ) -> None:
        """execute() with no preceding pre_check has nothing stashed, so it must
        fetch fresh — the reuse is an optimization, never a dependency."""
        tool = CancelOrderTool()

        with patch.object(
            tool._order_repo,
            "get_for_user",
            wraps=tool._order_repo.get_for_user,
        ) as spy:
            result = await tool.execute({"order_id": "ORD-002", "reason": "x"}, owner)

        assert result.success is True
        assert spy.call_count == 1

    @pytest.mark.asyncio
    async def test_rejected_pre_check_stashes_nothing(
        self, owner: SessionContext
    ) -> None:
        """A rejecting pre_check must not stash, so execute re-fetches and
        re-applies its own guard independently (preserves the create_refund
        pre_check-blocks / execute-proceeds disagreement)."""
        tool = CancelOrderTool()
        params = {"order_id": "ORD-001", "reason": "too late"}  # shipped -> reject

        check = await tool.pre_check(params, owner)

        assert check.passed is False
        assert "_mutation_order" not in owner.slots
