"""Business scenario FSM implementations."""
from __future__ import annotations

from open_chat_shop.core.scenarios.complaint import ComplaintScenarioFSM
from open_chat_shop.core.scenarios.order_inquiry import OrderInquiryScenarioFSM

__all__ = ["ComplaintScenarioFSM", "OrderInquiryScenarioFSM"]
